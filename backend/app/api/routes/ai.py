from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import DbSession, audit_context, require_permission
from app.core.roles import Permission
from app.models.user import User
from app.schemas.ai import CheckOut, DocumentAssistIn, DocumentAssistOut, ExplanationIn, ExplanationOut, StatusOut
from app.services import ai_service

router = APIRouter(tags=["ai"])

SystemReader = Annotated[User, Depends(require_permission(Permission.SYSTEM_READ))]
Reader = Annotated[User, Depends(require_permission(Permission.DOCUMENTS_READ))]
# Requesting AI spends budget and may send data out: case workers only. Application-level edit access is
# checked in the service, so a reader still gets the stored result and the deterministic fallback.
Requester = Annotated[User, Depends(require_permission(Permission.VALIDATION_RUN))]
Admin = Annotated[User, Depends(require_permission(Permission.USERS_MANAGE))]
DOC = "/ai/applications/{application_id}/documents/{document_id}"


@router.get("/ai/status", response_model=StatusOut)
def ai_status(db: DbSession, _: SystemReader) -> StatusOut:
    """Provider state and health, egress policy, limits and today's spend. Never includes credentials."""
    return StatusOut(**ai_service.status(db))


@router.post("/ai/status/check", response_model=CheckOut)
def ai_check(request: Request, db: DbSession, user: Admin) -> CheckOut:
    """Reachability and credentials check against the provider. Spends no tokens."""
    return CheckOut(**ai_service.check(db, audit_context(request, user)))


@router.get("/ai/explanations", response_model=ExplanationOut)
def get_explanation(
    db: DbSession,
    user: Reader,
    subject_type: Annotated[str, Query(pattern="^(review_item|evidence_finding|application)$")],
    subject_id: Annotated[str, Query(min_length=1, max_length=32)],
) -> ExplanationOut:
    """The latest stored AI explanation (if any) with the deterministic result and fallback explanation."""
    return ExplanationOut(**ai_service.get_explanation(db, user, subject_type, subject_id))


@router.post("/ai/explanations", response_model=ExplanationOut)
def request_explanation(body: ExplanationIn, request: Request, db: DbSession, user: Requester) -> ExplanationOut:
    """Ask for a plain-language explanation. Reuses the stored answer for identical input unless ``refresh``."""
    return ExplanationOut(
        **ai_service.explain(
            db, audit_context(request, user), user, body.subject_type, body.subject_id, refresh=body.refresh
        )
    )


@router.get(DOC, response_model=DocumentAssistOut)
def document_assist(application_id: str, document_id: str, db: DbSession, user: Reader) -> DocumentAssistOut:
    return DocumentAssistOut(**ai_service.document_assist(db, user, application_id, document_id))


@router.post(DOC + "/classification", response_model=DocumentAssistOut)
def classify(
    application_id: str, document_id: str, body: DocumentAssistIn, request: Request, db: DbSession, user: Requester
) -> DocumentAssistOut:
    return DocumentAssistOut(
        **ai_service.classify(db, audit_context(request, user), user, application_id, document_id, refresh=body.refresh)
    )


@router.post(DOC + "/field-suggestions", response_model=DocumentAssistOut)
def field_suggestions(
    application_id: str, document_id: str, body: DocumentAssistIn, request: Request, db: DbSession, user: Requester
) -> DocumentAssistOut:
    return DocumentAssistOut(
        **ai_service.suggest_fields(
            db, audit_context(request, user), user, application_id, document_id, refresh=body.refresh
        )
    )
