from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.api.deps import DbSession, require_permission
from app.core.errors import DomainError
from app.core.roles import Permission
from app.models.audit import AuditEvent
from app.models.user import User
from app.schemas.audit import AuditEventOut, ChainVerificationOut
from app.schemas.common import Page
from app.services import audit_service

router = APIRouter(prefix="/audit", tags=["audit"])

Reader = Annotated[User, Depends(require_permission(Permission.AUDIT_READ))]


@router.get("/events", response_model=Page[AuditEventOut])
def list_events(
    db: DbSession,
    reader: Reader,
    action: Annotated[
        str | None, Query(max_length=100, description='Exact action, or a prefix ending in "." (e.g. "rule.")')
    ] = None,
    entity_type: Annotated[str | None, Query(max_length=60)] = None,
    entity_id: Annotated[str | None, Query(max_length=64)] = None,
    actor_id: Annotated[str | None, Query(max_length=32)] = None,
    outcome: Annotated[str | None, Query(pattern="^(success|failure)$")] = None,
    date_from: Annotated[date | None, Query(alias="from", description="UTC date, inclusive")] = None,
    date_to: Annotated[date | None, Query(alias="to", description="UTC date, inclusive")] = None,
    q: Annotated[str | None, Query(max_length=100, description="Text in the summary or actor email")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[AuditEventOut]:
    filters = [audit_service.institution_scope(reader)]
    if action:
        filters.append(AuditEvent.action.startswith(action) if action.endswith(".") else AuditEvent.action == action)
    if entity_type:
        filters.append(AuditEvent.entity_type == entity_type)
    if entity_id:
        filters.append(AuditEvent.entity_id == entity_id)
    if actor_id:
        filters.append(AuditEvent.actor_id == actor_id)
    if outcome:
        filters.append(AuditEvent.outcome == outcome)
    if date_from and date_to and date_from > date_to:
        raise DomainError("The start date is after the end date", code="invalid_window", status_code=422)
    if date_from:
        filters.append(AuditEvent.occurred_at >= datetime.combine(date_from, time.min, tzinfo=UTC))
    if date_to:
        filters.append(AuditEvent.occurred_at < datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=UTC))
    if q:
        term = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        filters.append(AuditEvent.summary.ilike(term, escape="\\") | AuditEvent.actor_email.ilike(term, escape="\\"))
    total = db.execute(select(func.count()).select_from(AuditEvent).where(*filters)).scalar_one()
    rows = db.execute(
        select(AuditEvent).where(*filters).order_by(AuditEvent.seq.desc()).limit(limit).offset(offset)
    ).scalars()
    return Page(items=[AuditEventOut.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.get("/actions", response_model=list[str])
def list_actions(db: DbSession, reader: Reader) -> list[str]:
    """Distinct recorded actions, for filter menus."""
    stmt = select(AuditEvent.action).where(audit_service.institution_scope(reader)).distinct().order_by(AuditEvent.action)
    return list(db.execute(stmt).scalars())


@router.get("/verify", response_model=ChainVerificationOut)
def verify(db: DbSession, _: Reader) -> ChainVerificationOut:
    result = audit_service.verify_chain(db)
    return ChainVerificationOut(**result.__dict__)
