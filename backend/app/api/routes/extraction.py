from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, status
from fastapi.responses import Response
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import DbSession, audit_context, require_permission
from app.core.roles import Permission
from app.db.session import get_session_factory
from app.extraction import baseline
from app.extraction.ocr import OcrEngine, get_ocr_engine
from app.models.application import ApplicationStatus
from app.models.extraction import ExtractionRun
from app.models.user import User
from app.schemas.application import DocumentOut, UserRef
from app.schemas.extraction import (
    CorrectionIn,
    CorrectionOut,
    ExtractionView,
    ExtractorInfo,
    FieldOut,
    PageOut,
    PageTextOut,
    ReprocessIn,
    RunOut,
)
from app.services import application_service, document_service, extraction_service, processing
from app.services.storage import LocalStorage, get_storage

router = APIRouter(prefix="/applications/{application_id}/documents/{document_id}", tags=["extraction"])

Reader = Annotated[User, Depends(require_permission(Permission.DOCUMENTS_READ))]
Writer = Annotated[User, Depends(require_permission(Permission.APPLICATIONS_WRITE))]
Storage = Annotated[LocalStorage, Depends(get_storage)]
Factory = Annotated[sessionmaker, Depends(get_session_factory)]
Ocr = Annotated[OcrEngine, Depends(get_ocr_engine)]

EXTRACTOR_INFO = ExtractorInfo(
    name=baseline.EXTRACTOR, version=baseline.VERSION, kind="deterministic_baseline", limitations=baseline.LIMITATIONS
)


def _view(db: Session, user: User, run: ExtractionRun, application_id: str, document_id: str) -> ExtractionView:
    doc = document_service.get(db, user, application_id, document_id)
    corrections = extraction_service.corrections_by_key(db, doc.id)
    fields = []
    for f in run.fields:
        history = corrections.get(f.field_key, [])
        extracted = f.normalized_value or f.raw_value
        if history:
            effective, source = history[-1].normalized_value, "correction"
        elif f.normalized_value is not None:
            effective, source = f.normalized_value, "normalized"
        elif f.raw_value is not None:
            effective, source = f.raw_value, "raw"
        else:
            effective, source = None, "none"
        fields.append(
            FieldOut(
                id=f.id,
                field_key=f.field_key,
                field_type=f.field_type,
                label=f.label,
                status=f.status,
                raw_value=f.raw_value,
                normalized_value=f.normalized_value,
                normalized_data=f.normalized_data,
                normalization_note=f.normalization_note,
                method=f.method,
                matched_label=f.matched_label,
                page_number=f.page_number,
                bbox=f.bbox,
                confidence=f.confidence,
                quality_flags=f.quality_flags,
                alternatives=f.alternatives,
                corrections=[CorrectionOut.model_validate(c) for c in history],
                effective_value=effective,
                effective_source=source,
                correction_based_on_other_value=bool(history) and history[-1].based_on_value != extracted,
            )
        )
    editable = application_service.can_edit(user, doc.application) and doc.application.status not in (
        ApplicationStatus.ARCHIVED.value,
        ApplicationStatus.COMPLETED.value,
    )
    return ExtractionView(
        document_id=doc.id,
        document_status=doc.status,
        detected_mime=doc.detected_mime,
        run=RunOut.model_validate(run),
        extractor=EXTRACTOR_INFO,
        pages=[PageOut.model_validate(p) for p in run.pages],
        fields=fields,
        can_correct=editable and run.is_current,
        can_reprocess=editable and doc.status not in ("queued", "processing"),
        preview_supported=True,  # pages are rendered server-side for every accepted format
    )


@router.get("/extraction", response_model=ExtractionView)
def get_extraction(application_id: str, document_id: str, db: DbSession, user: Reader) -> ExtractionView:
    """The current extraction run with pages, fields, corrections and effective values. 404 `not_extracted` if none."""
    _, run = extraction_service.current_run(db, user, application_id, document_id)
    return _view(db, user, run, application_id, document_id)


@router.get("/extraction/runs", response_model=list[RunOut])
def list_runs(application_id: str, document_id: str, db: DbSession, user: Reader) -> list[RunOut]:
    return [RunOut.model_validate(r) for r in extraction_service.list_runs(db, user, application_id, document_id)]


@router.get("/extraction/runs/{run_id}", response_model=ExtractionView)
def get_run(application_id: str, document_id: str, run_id: str, db: DbSession, user: Reader) -> ExtractionView:
    """Any historical run, for reproducibility. Corrections are shown, but can only be added to the current run."""
    _, run = extraction_service.get_run(db, user, application_id, document_id, run_id)
    return _view(db, user, run, application_id, document_id)


@router.get("/pages/{page_number}/text", response_model=PageTextOut)
def page_text(application_id: str, document_id: str, page_number: int, db: DbSession, user: Reader) -> PageTextOut:
    _, run = extraction_service.current_run(db, user, application_id, document_id)
    page = extraction_service.page_of(run, page_number)
    return PageTextOut(
        page_number=page.page_number,
        text_source=page.text_source,
        raw_text=page.raw_text,
        normalized_text=page.normalized_text,
    )


@router.get(
    "/pages/{page_number}/image",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
def page_image(
    application_id: str,
    document_id: str,
    page_number: int,
    db: DbSession,
    user: Reader,
    storage: Storage,
    scale: Annotated[float, Query(ge=0.25, le=3.0)] = 1.5,
) -> Response:
    """PNG rendering of the page as displayed. Field bounding boxes use the same space (scaled by `scale` for PDFs)."""
    png = extraction_service.render_page(db, user, storage, application_id, document_id, page_number, scale)
    return Response(
        png,
        media_type="image/png",
        headers={"Cache-Control": "private, no-store", "Content-Security-Policy": "default-src 'none'; sandbox"},
    )


@router.post("/reprocess", response_model=DocumentOut, status_code=status.HTTP_202_ACCEPTED)
def reprocess(
    application_id: str,
    document_id: str,
    body: ReprocessIn,
    request: Request,
    background: BackgroundTasks,
    db: DbSession,
    user: Writer,
    storage: Storage,
    factory: Factory,
    ocr: Ocr,
) -> DocumentOut:
    """Queue inspection + extraction again. Without `force`, an identical earlier run is reused (idempotent)."""
    from app.api.routes.applications import _doc_out

    job = document_service.reprocess(
        db, audit_context(request, user), user, application_id, document_id, force=body.force
    )
    processing.schedule(background, job.id, factory, storage, getattr(request.state, "request_id", None), ocr)
    db.expire_all()
    return _doc_out(document_service.get(db, user, application_id, document_id), user)


@router.post(
    "/extraction/fields/{field_id}/corrections", response_model=CorrectionOut, status_code=status.HTTP_201_CREATED
)
def correct_field(
    application_id: str,
    document_id: str,
    field_id: str,
    body: CorrectionIn,
    request: Request,
    db: DbSession,
    user: Writer,
) -> CorrectionOut:
    """Append a correction. The original extracted value is never modified; history is kept in full."""
    c = extraction_service.add_correction(
        db, audit_context(request, user), user, application_id, document_id, field_id, body.value, body.reason
    )
    return CorrectionOut(
        id=c.id,
        value=c.value,
        normalized_value=c.normalized_value,
        reason=c.reason,
        based_on_value=c.based_on_value,
        based_on_field_id=c.based_on_field_id,
        actor=UserRef.model_validate(user),
        created_at=c.created_at,
    )
