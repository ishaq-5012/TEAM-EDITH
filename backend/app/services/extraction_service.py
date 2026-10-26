"""Read access to extraction results, page rendering and human corrections."""

from __future__ import annotations

import hashlib
import io
import secrets

import pymupdf
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import DomainError, NotFoundError
from app.extraction.definitions import FieldDefinition, FieldType, load_definitions
from app.extraction.normalizers import normalize
from app.extraction.pages import load_image
from app.models.application import Document
from app.models.extraction import DocumentPage, ExtractedField, ExtractionRun, FieldCorrection
from app.models.user import User
from app.services import application_service, audit_service, document_service
from app.services.audit_service import AuditContext
from app.services.document_service import IntegrityFailure
from app.services.storage import LocalStorage

MAX_RENDER_PIXELS = 20_000_000


class NotExtracted(NotFoundError):
    code = "not_extracted"


class InvalidCorrection(DomainError):
    status_code = 422
    code = "invalid_value"


def current_run(db: Session, user: User, application_id: str, document_id: str) -> tuple[Document, ExtractionRun]:
    doc = document_service.get(db, user, application_id, document_id)
    run = db.execute(
        select(ExtractionRun).where(ExtractionRun.document_id == doc.id, ExtractionRun.is_current.is_(True))
    ).scalar_one_or_none()
    if run is None:
        raise NotExtracted("This document has not been extracted yet")
    return doc, run


def get_run(
    db: Session, user: User, application_id: str, document_id: str, run_id: str
) -> tuple[Document, ExtractionRun]:
    doc = document_service.get(db, user, application_id, document_id)
    run = db.get(ExtractionRun, run_id)
    if run is None or run.document_id != doc.id:
        raise NotFoundError("Extraction run not found")
    return doc, run


def list_runs(db: Session, user: User, application_id: str, document_id: str) -> list[ExtractionRun]:
    doc = document_service.get(db, user, application_id, document_id)
    return list(
        db.execute(
            select(ExtractionRun).where(ExtractionRun.document_id == doc.id).order_by(ExtractionRun.finished_at.desc())
        ).scalars()
    )


def corrections_by_key(db: Session, document_id: str) -> dict[str, list[FieldCorrection]]:
    rows = db.execute(
        select(FieldCorrection).where(FieldCorrection.document_id == document_id).order_by(FieldCorrection.created_at)
    ).scalars()
    out: dict[str, list[FieldCorrection]] = {}
    for c in rows:
        out.setdefault(c.field_key, []).append(c)
    return out


def page_of(run: ExtractionRun, page_number: int) -> DocumentPage:
    page = next((p for p in run.pages if p.page_number == page_number), None)
    if page is None:
        raise NotFoundError("Page not found")
    return page


def _verified_bytes(storage: LocalStorage, doc: Document) -> bytes:
    data = storage.read(doc.storage_key)
    if not secrets.compare_digest(hashlib.sha256(data).hexdigest(), doc.sha256):
        raise IntegrityFailure("The stored file failed its integrity check and will not be rendered")
    return data


def render_page(
    db: Session,
    user: User,
    storage: LocalStorage,
    application_id: str,
    document_id: str,
    page_number: int,
    scale: float,
) -> bytes:
    """PNG of the page as displayed (rotation/EXIF applied): the same space as stored field coordinates."""
    doc = document_service.get(db, user, application_id, document_id)
    data = _verified_bytes(storage, doc)
    if doc.detected_mime == "application/pdf":
        with pymupdf.open(stream=data, filetype="pdf") as pdf:
            if not 1 <= page_number <= pdf.page_count:
                raise NotFoundError("Page not found")
            page = pdf[page_number - 1]
            pixels = page.rect.width * scale * page.rect.height * scale
            if pixels > MAX_RENDER_PIXELS:
                scale *= (MAX_RENDER_PIXELS / pixels) ** 0.5
            return page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).tobytes("png")
    if page_number != 1:
        raise NotFoundError("Page not found")
    image = load_image(data)
    target = (max(1, round(image.width * min(scale, 1.0))), max(1, round(image.height * min(scale, 1.0))))
    if target != image.size:
        image = image.resize(target)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _definition_for(field: ExtractedField) -> FieldDefinition:
    definitions, _ = load_definitions(get_settings().field_definitions_path)
    found = next((d for d in definitions.fields if d.key == field.field_key), None)
    # If definitions changed since extraction, validate with the type the field was extracted as.
    return found or FieldDefinition(
        key=field.field_key, label=field.label, type=FieldType(field.field_type), labels=[field.label]
    )


def add_correction(
    db: Session,
    ctx: AuditContext,
    user: User,
    application_id: str,
    document_id: str,
    field_id: str,
    value: str,
    reason: str,
    *,
    commit: bool = True,
) -> FieldCorrection:
    """Append a human correction. The extracted field itself is never modified.

    ``commit=False`` lets a caller (the review center) record the correction and its own history entry in one
    transaction.
    """
    app = application_service.get_for_edit(db, user, application_id)
    application_service.ensure_mutable(app)
    doc, run = current_run(db, user, application_id, document_id)
    field = db.get(ExtractedField, field_id)
    if field is None or field.document_id != doc.id:
        raise NotFoundError("Field not found")
    if field.run_id != run.id:
        raise DomainError(
            "Corrections can only be made against the current extraction", code="stale_field", status_code=409
        )
    norm = normalize(value, _definition_for(field), from_ocr=False)
    if norm.status == "invalid":
        raise InvalidCorrection(norm.note or "The value is not valid for this field")
    if norm.status == "ambiguous":
        raise InvalidCorrection(f"{norm.note} Enter the date unambiguously, for example as YYYY-MM-DD.")
    previous = corrections_by_key(db, doc.id).get(field.field_key, [])
    before = previous[-1].normalized_value if previous else (field.normalized_value or field.raw_value)
    correction = FieldCorrection(
        document_id=doc.id,
        field_key=field.field_key,
        based_on_field_id=field.id,
        based_on_value=field.normalized_value or field.raw_value,
        value=value.strip(),
        normalized_value=norm.value or value.strip(),
        reason=reason.strip(),
        actor_id=user.id,
    )
    db.add(correction)
    db.flush()
    audit_service.record(
        db,
        ctx,
        "extraction.field_corrected",
        entity_type="application",
        entity_id=app.id,
        summary=f"Corrected {field.label} on “{doc.original_filename}”",
        data={
            "document_id": doc.id,
            "field_key": field.field_key,
            "field_id": field.id,
            "before": before,
            "after": correction.normalized_value,
            "original_extracted": field.raw_value,
            "reason": correction.reason,
        },
    )
    if commit:
        db.commit()
    else:
        db.flush()
    return correction
