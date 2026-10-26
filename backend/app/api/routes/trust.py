from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import DbSession, audit_context, require_permission
from app.core.roles import Permission
from app.models.user import User
from app.schemas.trust import (
    AppRef,
    CapabilitiesOut,
    DocRef,
    HistoryOut,
    OverviewOut,
    OverviewRow,
    VerificationOut,
    VerificationSummary,
)
from app.services import trust_service
from app.services.storage import LocalStorage, get_storage

router = APIRouter(tags=["trust"])

Reader = Annotated[User, Depends(require_permission(Permission.DOCUMENTS_READ))]
Runner = Annotated[User, Depends(require_permission(Permission.VALIDATION_RUN))]
Storage = Annotated[LocalStorage, Depends(get_storage)]
DOC = "/applications/{application_id}/documents/{document_id}/verifications"


@router.get("/trust/capabilities", response_model=CapabilitiesOut)
def capabilities(_: Reader) -> CapabilitiesOut:
    """Which verification capabilities are implemented, enabled, or need external infrastructure."""
    return CapabilitiesOut(**trust_service.capabilities())


@router.get("/trust/documents", response_model=OverviewOut)
def overview(
    db: DbSession,
    user: Reader,
    application_id: Annotated[str | None, Query(max_length=32)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OverviewOut:
    rows, total = trust_service.overview(db, user, application_id, limit, offset)
    return OverviewOut(
        items=[
            OverviewRow(
                document=DocRef.model_validate(d),
                application=AppRef.model_validate(a),
                latest=VerificationSummary.model_validate(v) if v else None,
            )
            for d, a, v in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(DOC, response_model=HistoryOut)
def history(application_id: str, document_id: str, db: DbSession, user: Reader) -> HistoryOut:
    h = trust_service.history(db, user, application_id, document_id)
    return HistoryOut(
        application=AppRef.model_validate(h["application"]),
        document=DocRef.model_validate(h["document"]),
        verifications=[VerificationSummary.model_validate(v) for v in h["verifications"]],
        same_hash_documents=h["same_hash_documents"],
        can_verify=h["can_verify"],
    )


@router.post(DOC, response_model=VerificationOut, status_code=status.HTTP_201_CREATED)
def verify(
    application_id: str, document_id: str, request: Request, db: DbSession, user: Runner, storage: Storage
) -> VerificationOut:
    """Run every configured check now. Each run is stored immutably; earlier runs are never changed."""
    v = trust_service.verify(db, audit_context(request, user), user, storage, application_id, document_id)
    return VerificationOut.model_validate(v)


@router.get(DOC + "/{verification_id}", response_model=VerificationOut)
def get_verification(
    application_id: str, document_id: str, verification_id: str, db: DbSession, user: Reader
) -> VerificationOut:
    return VerificationOut.model_validate(trust_service.get(db, user, application_id, document_id, verification_id))
