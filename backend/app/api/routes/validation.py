from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import DbSession, audit_context, require_permission
from app.core.roles import Permission
from app.models.user import User
from app.schemas.rules import ValidationRunIn, ValidationRunOut, ValidationRunSummary
from app.services import rule_service, validation_service

router = APIRouter(prefix="/applications/{application_id}/validation-runs", tags=["validation"])

Reader = Annotated[User, Depends(require_permission(Permission.APPLICATIONS_READ))]
Runner = Annotated[User, Depends(require_permission(Permission.VALIDATION_RUN))]


def _out(db, vr) -> ValidationRunOut:  # noqa: ANN001
    out = ValidationRunOut.model_validate(vr)
    out.disclaimer = rule_service.DISCLAIMER
    out.next_run_ids = validation_service.next_run_ids(db, vr.id)
    return out


@router.post("", response_model=ValidationRunOut, status_code=status.HTTP_201_CREATED)
def run_validation(
    application_id: str, body: ValidationRunIn, request: Request, db: DbSession, user: Runner
) -> ValidationRunOut:
    """Evaluate every rule version in force on `evaluation_date` (default today) against a fresh input snapshot."""
    vr = validation_service.run(db, audit_context(request, user), user, application_id, body.evaluation_date)
    return _out(db, vr)


@router.get("", response_model=list[ValidationRunSummary])
def list_runs(application_id: str, db: DbSession, user: Reader) -> list[ValidationRunSummary]:
    return [ValidationRunSummary.model_validate(r) for r in validation_service.list_runs(db, user, application_id)]


@router.get("/{run_id}", response_model=ValidationRunOut)
def get_run(application_id: str, run_id: str, db: DbSession, user: Reader) -> ValidationRunOut:
    return _out(db, validation_service.get(db, user, application_id, run_id))


@router.get("/{run_id}/reproduction")
def reproduce(application_id: str, run_id: str, db: DbSession, user: Reader) -> dict:
    """Re-evaluate the stored snapshot with the stored rule definitions and report any difference. Read-only."""
    return validation_service.reproduce(db, user, application_id, run_id)
