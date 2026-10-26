"""Document upload validation, storage, listing, download and processing retry.

Upload pipeline (nothing is committed until every check passes):

1. caller has edit rights; application is not archived/completed; per-application document cap
2. stream into private storage with a hard size limit while hashing (SHA-256)
3. type from magic bytes only; the declared MIME type and the filename extension must agree with it
4. structural validation: PDF parses, is not encrypted, has 1..max pages; images decode within a pixel limit
5. reject a duplicate of a document already in the same application (same SHA-256)
6. insert document + queued processing job; on any failure the stored file is removed
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import BinaryIO

import pymupdf
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ConflictError, DomainError, NotFoundError
from app.db.base import utcnow
from app.models.application import Application, ApplicationStatus, Document, DocumentStatus, JobStatus, ProcessingJob
from app.models.user import User
from app.services import application_service, audit_service
from app.services.audit_service import AuditContext
from app.services.storage import LocalStorage, StoredObject, sanitize_display_name

logger = logging.getLogger("verifyflow.documents")

PROCESSING_JOB = "inspection_and_extraction"

# Detected MIME -> accepted filename extensions and accepted declared MIME aliases.
SUPPORTED: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "application/pdf": (frozenset({".pdf"}), frozenset({"application/pdf", "application/x-pdf"})),
    "image/png": (frozenset({".png"}), frozenset({"image/png"})),
    "image/jpeg": (frozenset({".jpg", ".jpeg"}), frozenset({"image/jpeg", "image/jpg", "image/pjpeg"})),
    "image/tiff": (frozenset({".tif", ".tiff"}), frozenset({"image/tiff", "image/tif"})),
}
# Clients may legitimately not know the type; these are treated as "not declared".
UNDECLARED_MIME = frozenset({"", "application/octet-stream", "binary/octet-stream"})


class StorageUnavailable(DomainError):
    status_code = 503
    code = "storage_unavailable"


class TypeMismatch(DomainError):
    status_code = 415


class InvalidDocument(DomainError):
    status_code = 422
    code = "invalid_document"


class DuplicateDocument(ConflictError):
    code = "duplicate_document"

    def __init__(self, existing: Document):
        super().__init__(
            f"This file is already in the application as “{existing.original_filename}” (identical SHA-256)."
        )
        self.existing_id = existing.id


# ------------------------------------------------------------------ validation


def _check_declared_type(filename: str, declared_mime: str | None, detected_mime: str) -> None:
    extensions, aliases = SUPPORTED[detected_mime]
    ext = Path(filename).suffix.lower()
    if ext not in extensions:
        raise TypeMismatch(
            f"The file extension “{ext or '(none)'}” does not match the file's actual content ({detected_mime}).",
            code="extension_mismatch",
        )
    declared = (declared_mime or "").split(";")[0].strip().lower()
    if declared not in UNDECLARED_MIME and declared not in aliases:
        raise TypeMismatch(
            f"The declared type “{declared}” does not match the file's actual content ({detected_mime}).",
            code="mime_mismatch",
        )


def validate_structure(path: Path, detected_mime: str) -> int | None:
    """Return the page count (PDF) or None (images). Raises InvalidDocument when unusable."""
    settings = get_settings()
    if detected_mime == "application/pdf":
        # Parse from memory (uploads are size-capped): MuPDF can keep an OS handle open on files it
        # fails to parse, which on Windows would block deleting the rejected upload.
        try:
            doc = pymupdf.open(stream=path.read_bytes(), filetype="pdf")
        except Exception as exc:  # noqa: BLE001 - any parser failure means the PDF is unusable
            raise InvalidDocument(f"The PDF could not be parsed: {exc}", code="pdf_invalid") from None
        with doc:
            if doc.needs_pass or doc.is_encrypted:
                raise InvalidDocument("Password-protected or encrypted PDFs are not supported", code="pdf_encrypted")
            pages = doc.page_count
            if pages < 1:
                raise InvalidDocument("The PDF has no pages", code="pdf_empty")
            if pages > settings.max_pdf_pages:
                raise InvalidDocument(
                    f"The PDF has {pages} pages; the limit is {settings.max_pdf_pages}", code="pdf_too_many_pages"
                )
            return pages
    # Raster images: header-level size check first (cheap), then a full decode check.
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as img:
                width, height = img.size
                if width * height > settings.max_image_pixels:
                    raise InvalidDocument(
                        f"The image is {width}×{height} px; the limit is {settings.max_image_pixels:,} pixels",
                        code="image_too_large",
                    )
                img.verify()
            with Image.open(path) as img:
                img.load()
    except InvalidDocument:
        raise
    except Exception as exc:  # noqa: BLE001 - corrupt or hostile image data
        raise InvalidDocument(f"The image could not be decoded: {exc}", code="image_invalid") from None
    return None


# ------------------------------------------------------------------ upload


@dataclass(frozen=True)
class UploadResult:
    document: Document
    job: ProcessingJob


def upload(
    db: Session, ctx: AuditContext, user: User, storage: LocalStorage, application_id: str, *,
    stream: BinaryIO, filename: str | None, declared_mime: str | None, document_type: str | None,
) -> UploadResult:
    settings = get_settings()
    app = application_service.get_for_edit(db, user, application_id)
    application_service.ensure_mutable(app)
    if app.status == ApplicationStatus.COMPLETED.value:
        raise ConflictError("This application is completed. Reopen it to add documents.", code="application_completed")
    if app.review_stage == "audit":
        raise ConflictError("The auditor must return this application before documents can be added.", code="audit_pending")
    count = db.execute(select(func.count()).select_from(Document).where(Document.application_id == app.id)).scalar_one()
    if count >= settings.max_documents_per_application:
        raise ConflictError(
            f"An application can hold at most {settings.max_documents_per_application} documents",
            code="document_limit_reached",
        )

    display_name = sanitize_display_name(filename)
    try:
        stored: StoredObject = storage.save(stream)
    except OSError as exc:
        logger.error("Storage write failed for application %s: %s", app.id, exc)
        audit_service.record(
            db, ctx, "document.upload_failed", entity_type="application", entity_id=app.id, outcome="failure",
            summary="Upload failed: storage unavailable", data={"filename": display_name, "reason": "storage_error"},
        )
        db.commit()
        raise StorageUnavailable("Document storage is unavailable. Nothing was saved; please retry.") from None
    except DomainError as exc:
        # Size limit, empty file or unsupported content: the storage layer already removed the partial file.
        audit_service.record(
            db, ctx, "document.upload_rejected", entity_type="application", entity_id=app.id, outcome="failure",
            summary=f"Rejected upload “{display_name}”: {exc.code}",
            data={"filename": display_name, "reason": exc.code},
        )
        db.commit()
        raise

    try:
        _check_declared_type(display_name, declared_mime, stored.detected_mime)
        page_count = validate_structure(storage.path(stored.storage_key), stored.detected_mime)
        existing = db.execute(
            select(Document).where(Document.application_id == app.id, Document.sha256 == stored.sha256)
        ).scalar_one_or_none()
        if existing is not None:
            raise DuplicateDocument(existing)

        doc = Document(
            application_id=app.id,
            original_filename=display_name,
            document_type=(document_type or "").strip() or None,
            declared_mime=(declared_mime or None) and declared_mime[:120],
            detected_mime=stored.detected_mime,
            size_bytes=stored.size_bytes,
            sha256=stored.sha256,
            storage_key=stored.storage_key,
            page_count=page_count,
            status=DocumentStatus.QUEUED.value,
            uploaded_by_id=user.id,
        )
        db.add(doc)
        db.flush()
        job = ProcessingJob(document_id=doc.id, kind=PROCESSING_JOB, requested_by_id=user.id, attempt=1)
        db.add(job)
        application_service.mark_processing(app)
        audit_service.record(
            db, ctx, "document.uploaded", entity_type="application", entity_id=app.id,
            summary=f"Uploaded “{display_name}” to {app.reference}",
            data={
                "document_id": doc.id, "filename": display_name, "sha256": stored.sha256,
                "size_bytes": stored.size_bytes, "detected_mime": stored.detected_mime, "page_count": page_count,
            },
        )
        db.commit()
    except DomainError as exc:
        db.rollback()
        storage.delete(stored.storage_key)
        audit_service.record(
            db, ctx, "document.upload_rejected", entity_type="application", entity_id=app.id, outcome="failure",
            summary=f"Rejected upload “{display_name}”: {exc.code}",
            data={"filename": display_name, "reason": exc.code, "sha256": stored.sha256},
        )
        db.commit()
        raise
    except IntegrityError:
        # Concurrent upload of the same file won the unique (application_id, sha256) race.
        db.rollback()
        storage.delete(stored.storage_key)
        raise ConflictError(
            "This file was just added to the application by another upload", code="duplicate_document"
        ) from None
    except Exception:
        db.rollback()
        storage.delete(stored.storage_key)
        raise
    db.refresh(doc)
    return UploadResult(doc, job)


# ------------------------------------------------------------------ read / download / retry


def list_for_application(db: Session, user: User, application_id: str) -> list[Document]:
    app = application_service.get_for_read(db, user, application_id)
    return list(
        db.execute(select(Document).where(Document.application_id == app.id).order_by(Document.created_at)).scalars()
    )


def get(db: Session, user: User, application_id: str, document_id: str) -> Document:
    app = application_service.get_for_read(db, user, application_id)
    doc = db.get(Document, document_id)
    if doc is None or doc.application_id != app.id:
        raise NotFoundError("Document not found")
    return doc


class IntegrityFailure(DomainError):
    status_code = 500
    code = "integrity_failure"


def open_for_download(
    db: Session, ctx: AuditContext, user: User, storage: LocalStorage, application_id: str, document_id: str
) -> tuple[Document, Path]:
    doc = get(db, user, application_id, document_id)
    if not storage.exists(doc.storage_key):
        raise NotFoundError("The stored file is missing")
    if not storage.verify(doc.storage_key, doc.sha256):
        audit_service.record(
            db, ctx, "document.integrity_failed", entity_type="application", entity_id=doc.application_id,
            outcome="failure", summary=f"Stored file for “{doc.original_filename}” no longer matches its SHA-256",
            data={"document_id": doc.id, "expected_sha256": doc.sha256},
        )
        db.commit()
        raise IntegrityFailure("The stored file failed its integrity check and will not be served")
    audit_service.record(
        db, ctx, "document.downloaded", entity_type="application", entity_id=doc.application_id,
        summary=f"Downloaded “{doc.original_filename}”", data={"document_id": doc.id},
    )
    db.commit()
    return doc, storage.path(doc.storage_key)


def is_stale(job: ProcessingJob) -> bool:
    if job.status not in (JobStatus.QUEUED.value, JobStatus.RUNNING.value):
        return False
    started = job.started_at or job.created_at
    return utcnow() - started > timedelta(minutes=get_settings().processing_stale_minutes)


def retry(db: Session, ctx: AuditContext, user: User, application_id: str, document_id: str) -> ProcessingJob:
    app: Application = application_service.get_for_edit(db, user, application_id)
    application_service.ensure_mutable(app)
    doc = get(db, user, application_id, document_id)
    last = doc.latest_job
    if not (doc.status == DocumentStatus.FAILED.value or (last is not None and is_stale(last))):
        raise ConflictError("Only failed or stalled processing can be retried", code="retry_not_allowed")
    if last is not None and last.status in (JobStatus.QUEUED.value, JobStatus.RUNNING.value):
        last.status = JobStatus.FAILED.value
        last.finished_at = utcnow()
        last.error_code = "interrupted"
        last.error_message = "Processing did not finish (server restart or crash) and was superseded by a retry"
        # Flush now: the one-active-job index must see this job leave "running" before the new job is inserted.
        db.flush()
    job = ProcessingJob(
        document_id=doc.id, kind=PROCESSING_JOB, requested_by_id=user.id, attempt=(last.attempt + 1 if last else 1)
    )
    db.add(job)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ConflictError("This document is already being processed", code="already_processing") from None
    doc.status = DocumentStatus.QUEUED.value
    application_service.mark_processing(app)
    audit_service.record(
        db, ctx, "document.processing_retried", entity_type="application", entity_id=app.id,
        summary=f"Retried processing of “{doc.original_filename}” (attempt {job.attempt})",
        data={"document_id": doc.id, "attempt": job.attempt},
    )
    db.commit()
    return job


def reprocess(
    db: Session, ctx: AuditContext, user: User, application_id: str, document_id: str, *, force: bool
) -> ProcessingJob:
    """Queue processing for a settled document. Without force, an identical earlier extraction is reused."""
    app: Application = application_service.get_for_edit(db, user, application_id)
    application_service.ensure_mutable(app)
    if app.status == ApplicationStatus.COMPLETED.value:
        raise ConflictError(
            "This application is completed. Reopen it to reprocess documents.", code="application_completed"
        )
    doc = get(db, user, application_id, document_id)
    if doc.status in (DocumentStatus.QUEUED.value, DocumentStatus.PROCESSING.value):
        raise ConflictError("This document is already being processed", code="already_processing")
    last = doc.latest_job
    job = ProcessingJob(
        document_id=doc.id, kind=PROCESSING_JOB, requested_by_id=user.id, force=force,
        attempt=(last.attempt + 1 if last else 1),
    )
    db.add(job)
    try:
        db.flush()  # the partial unique index rejects a second active job, even from a concurrent request
    except IntegrityError:
        db.rollback()
        raise ConflictError("This document is already being processed", code="already_processing") from None
    doc.status = DocumentStatus.QUEUED.value
    application_service.mark_processing(app)
    audit_service.record(
        db, ctx, "document.reprocess_requested", entity_type="application", entity_id=app.id,
        summary=f"Reprocessing requested for “{doc.original_filename}”" + (" (forced)" if force else ""),
        data={"document_id": doc.id, "attempt": job.attempt, "force": force},
    )
    db.commit()
    return job
