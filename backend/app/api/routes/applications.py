from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, sessionmaker
from starlette.datastructures import UploadFile

from app.api.deps import DbSession, audit_context, require_permission
from app.core.config import get_settings
from app.core.errors import DomainError
from app.core.roles import Permission, has_permission
from app.db.session import get_session_factory
from app.extraction.ocr import OcrEngine, get_ocr_engine
from app.models.application import Application, ApplicationStatus, Document
from app.models.user import User
from app.schemas.auth import InstitutionOut
from app.schemas.application import (
    ApplicationCreate,
    ApplicationDetail,
    ApplicationListOut,
    ApplicationPermissions,
    ApplicationSummary,
    ApplicationUpdate,
    DocumentDetail,
    DocumentOut,
    JobOut,
    MemberAdd,
    MemberOut,
    TransitionRequest,
    UploadLimits,
    UserRef,
)
from app.services import application_service, document_service, processing
from app.services.storage import LocalStorage, get_storage

router = APIRouter(prefix="/applications", tags=["applications"])

Reader = Annotated[User, Depends(require_permission(Permission.APPLICATIONS_READ))]
Writer = Annotated[User, Depends(require_permission(Permission.APPLICATIONS_WRITE))]
Storage = Annotated[LocalStorage, Depends(get_storage)]
Factory = Annotated[sessionmaker, Depends(get_session_factory)]
Ocr = Annotated[OcrEngine, Depends(get_ocr_engine)]

# Multipart framing overhead allowed on top of the file-size limit.
_MULTIPART_OVERHEAD = 64 * 1024


def _summary(app: Application, document_count: int) -> ApplicationSummary:
    return ApplicationSummary(
        id=app.id, reference=app.reference, title=app.title, applicant_name=app.applicant_name,
        application_type=app.application_type, status=ApplicationStatus(app.status),
        review_stage=app.review_stage,
        owner=UserRef.model_validate(app.owner), document_count=document_count,
        created_at=app.created_at, updated_at=app.updated_at, is_synthetic=app.is_synthetic,
        institution=InstitutionOut.model_validate(app.institution) if app.institution else None,
    )


def _detail(db: Session, user: User, app: Application) -> ApplicationDetail:
    counts = application_service.document_counts(db, app.id)
    editable = application_service.can_edit(user, app)
    mutable = app.status != ApplicationStatus.ARCHIVED.value
    return ApplicationDetail(
        **_summary(app, sum(counts.values())).model_dump(),
        description=app.description,
        archived_at=app.archived_at,
        reviewer_completed_at=app.reviewer_completed_at,
        audited_at=app.audited_at,
        audit_note=app.audit_note,
        members=[MemberOut.model_validate(m) for m in sorted(app.members, key=lambda m: m.created_at)],
        document_status_counts=counts,
        permissions=ApplicationPermissions(
            can_edit=editable and mutable,
            can_upload=editable and app.review_stage == "reviewer" and app.status in ("draft", "processing", "needs_review"),
            can_manage_members=application_service.can_manage(user, app) and mutable,
            allowed_actions=application_service.allowed_actions(db, user, app),
        ),
    )


def _doc_out(doc: Document, user: User, cls: type[DocumentOut] = DocumentOut) -> DocumentOut:
    last = doc.latest_job
    can_retry = (
        application_service.can_edit(user, doc.application)
        and doc.application.status != ApplicationStatus.ARCHIVED.value
        and (doc.status == "failed" or (last is not None and document_service.is_stale(last)))
    )
    extra = {"jobs": [JobOut.model_validate(j) for j in doc.jobs]} if cls is DocumentDetail else {}
    return cls(
        id=doc.id, application_id=doc.application_id, original_filename=doc.original_filename,
        document_type=doc.document_type, declared_mime=doc.declared_mime, detected_mime=doc.detected_mime,
        size_bytes=doc.size_bytes, sha256=doc.sha256, page_count=doc.page_count, status=doc.status,
        uploaded_by=UserRef.model_validate(doc.uploaded_by), created_at=doc.created_at, updated_at=doc.updated_at,
        latest_job=JobOut.model_validate(last) if last else None, can_retry=can_retry, **extra,
    )


# ------------------------------------------------------------------ applications


@router.get("", response_model=ApplicationListOut)
def list_applications(
    db: DbSession,
    user: Reader,
    status_: Annotated[list[ApplicationStatus] | None, Query(alias="status")] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    application_type: Annotated[str | None, Query(max_length=60)] = None,
    scope: Literal["all", "mine"] = "all",
    sort: Literal["updated_desc", "created_desc", "reference_asc", "title_asc"] = "updated_desc",
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ApplicationListOut:
    """Applications visible to the caller: owned or member, or all with applications:read_all."""
    filters = application_service.ListFilters(
        statuses=[s.value for s in status_ or []], q=q or None, application_type=application_type or None,
        scope=scope, sort=sort, limit=limit, offset=offset,
    )
    rows, total = application_service.list_visible(db, user, filters)
    return ApplicationListOut(
        items=[_summary(a, n) for a, n in rows], total=total, limit=limit, offset=offset,
        application_types=application_service.distinct_types(db, user),
        can_create=has_permission(user.role, Permission.APPLICATIONS_WRITE),
    )


@router.post("", response_model=ApplicationDetail, status_code=status.HTTP_201_CREATED)
def create_application(body: ApplicationCreate, request: Request, db: DbSession, user: Writer) -> ApplicationDetail:
    app = application_service.create(
        db, audit_context(request, user), user, title=body.title, application_type=body.application_type,
        applicant_name=body.applicant_name, description=body.description,
    )
    return _detail(db, user, app)


@router.get("/upload-limits", response_model=UploadLimits)
def upload_limits(_: Reader) -> UploadLimits:
    s = get_settings()
    return UploadLimits(
        max_upload_bytes=s.max_upload_bytes, max_pdf_pages=s.max_pdf_pages,
        max_documents_per_application=s.max_documents_per_application,
        accepted={mime: sorted(exts) for mime, (exts, _) in document_service.SUPPORTED.items()},
    )


@router.get("/{application_id}", response_model=ApplicationDetail)
def get_application(application_id: str, db: DbSession, user: Reader) -> ApplicationDetail:
    return _detail(db, user, application_service.get_for_read(db, user, application_id))


@router.patch("/{application_id}", response_model=ApplicationDetail)
def update_application(
    application_id: str, body: ApplicationUpdate, request: Request, db: DbSession, user: Writer
) -> ApplicationDetail:
    changes = body.model_dump(exclude_unset=True)
    app = application_service.update(db, audit_context(request, user), user, application_id, changes)
    return _detail(db, user, app)


@router.post("/{application_id}/transitions", response_model=ApplicationDetail)
def transition_application(
    application_id: str, body: TransitionRequest, request: Request, db: DbSession, user: Reader
) -> ApplicationDetail:
    ctx = audit_context(request, user)
    app = application_service.transition(db, ctx, user, application_id, body.action, body.reason)
    return _detail(db, user, app)


@router.post("/{application_id}/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
def add_member(application_id: str, body: MemberAdd, request: Request, db: DbSession, user: Writer) -> MemberOut:
    ctx = audit_context(request, user)
    member = application_service.add_member(db, ctx, user, application_id, body.email, body.role)
    return MemberOut.model_validate(member)


@router.delete("/{application_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def remove_member(application_id: str, user_id: str, request: Request, db: DbSession, user: Writer) -> None:
    application_service.remove_member(db, audit_context(request, user), user, application_id, user_id)


# ------------------------------------------------------------------ documents


@router.get("/{application_id}/documents", response_model=list[DocumentOut])
def list_documents(application_id: str, db: DbSession, user: Reader) -> list[DocumentOut]:
    return [_doc_out(d, user) for d in document_service.list_for_application(db, user, application_id)]


_UPLOAD_OPENAPI = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "properties": {
                        "file": {"type": "string", "format": "binary"},
                        "document_type": {"type": "string", "maxLength": 60},
                    },
                }
            }
        },
    }
}


@router.post(
    "/{application_id}/documents",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
    openapi_extra=_UPLOAD_OPENAPI,
)
async def upload_document(
    application_id: str,
    request: Request,
    background: BackgroundTasks,
    db: DbSession,
    user: Writer,
    storage: Storage,
    factory: Factory,
    ocr: Ocr,
) -> DocumentOut:
    """multipart/form-data with one `file` part and an optional `document_type` field.

    The body is parsed here (not by FastAPI) so size limits are enforced before reading it.
    """
    settings = get_settings()
    length = request.headers.get("content-length")
    if length is None or not length.isdigit():
        raise DomainError("Uploads must declare Content-Length", code="length_required", status_code=411)
    if int(length) > settings.max_upload_bytes + _MULTIPART_OVERHEAD:
        raise DomainError(
            f"File exceeds the {settings.max_upload_bytes} byte limit", code="file_too_large", status_code=413
        )
    if not request.headers.get("content-type", "").startswith("multipart/form-data"):
        raise DomainError("Expected multipart/form-data", code="unsupported_media_type", status_code=415)
    try:
        form = await request.form(max_files=1, max_fields=4)
    except Exception as exc:  # noqa: BLE001 - malformed multipart bodies are a client error
        raise DomainError(f"Malformed multipart body: {exc}", code="invalid_multipart", status_code=400) from None
    try:
        file = form.get("file")
        if not isinstance(file, UploadFile):
            raise DomainError("A `file` part is required", code="file_required", status_code=422)
        document_type = form.get("document_type")
        if document_type is not None and (not isinstance(document_type, str) or len(document_type) > 60):
            raise DomainError("document_type must be text of at most 60 characters", code="invalid_document_type",
                              status_code=422)
        result = document_service.upload(
            db, audit_context(request, user), user, storage, application_id,
            stream=file.file, filename=file.filename, declared_mime=file.content_type,
            document_type=document_type,
        )
    finally:
        await form.close()
    processing.schedule(
        background, result.job.id, factory, storage, getattr(request.state, "request_id", None), ocr
    )
    return _doc_out(result.document, user)


@router.get("/{application_id}/documents/{document_id}", response_model=DocumentDetail)
def get_document(application_id: str, document_id: str, db: DbSession, user: Reader) -> DocumentOut:
    return _doc_out(document_service.get(db, user, application_id, document_id), user, DocumentDetail)


@router.get(
    "/{application_id}/documents/{document_id}/content",
    response_class=FileResponse,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
def download_document(
    application_id: str, document_id: str, request: Request, db: DbSession, user: Reader, storage: Storage
) -> FileResponse:
    """Streams the original file after an integrity check. Always an attachment, sandboxed by CSP."""
    doc, path = document_service.open_for_download(
        db, audit_context(request, user), user, storage, application_id, document_id
    )
    return FileResponse(
        path,
        media_type=doc.detected_mime,
        filename=doc.original_filename,
        content_disposition_type="attachment",
        headers={
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Cache-Control": "private, no-store",
            "X-Document-SHA256": doc.sha256,
        },
    )


@router.post("/{application_id}/documents/{document_id}/retry", response_model=DocumentOut)
def retry_processing(
    application_id: str, document_id: str, request: Request, background: BackgroundTasks,
    db: DbSession, user: Writer, storage: Storage, factory: Factory, ocr: Ocr,
) -> DocumentOut:
    job = document_service.retry(db, audit_context(request, user), user, application_id, document_id)
    processing.schedule(background, job.id, factory, storage, getattr(request.state, "request_id", None), ocr)
    db.expire_all()
    return _doc_out(document_service.get(db, user, application_id, document_id), user)
