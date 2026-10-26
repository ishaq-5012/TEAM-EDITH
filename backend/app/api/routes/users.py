from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, audit_context, require_permission
from app.core.errors import DomainError
from app.core.roles import Permission
from app.models.user import User
from app.schemas.auth import (
    PasswordReset,
    RevokeResult,
    RevokeSessionsRequest,
    SessionOut,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.schemas.common import Page
from app.services import session_service, user_service

router = APIRouter(prefix="/users", tags=["users"])

Reader = Annotated[User, Depends(require_permission(Permission.USERS_READ))]
Manager = Annotated[User, Depends(require_permission(Permission.USERS_MANAGE))]
SessionAdmin = Annotated[User, Depends(require_permission(Permission.SESSIONS_MANAGE))]


@router.get("", response_model=Page[UserOut])
def list_users(
    db: DbSession,
    actor: Reader,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[UserOut]:
    mine = User.institution_id == actor.institution_id
    total = db.execute(select(func.count()).select_from(User).where(mine)).scalar_one()
    rows = db.execute(select(User).where(mine).order_by(User.created_at).limit(limit).offset(offset)).scalars().all()
    return Page(items=[UserOut.model_validate(u) for u in rows], total=total, limit=limit, offset=offset)


@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: str, db: DbSession, actor: CurrentUser) -> UserOut:
    """Your own record, or anyone's with users:read. Others' records are 404 otherwise."""
    return UserOut.model_validate(user_service.get_visible_user(db, actor, user_id))


@router.get("/{user_id}/sessions", response_model=list[SessionOut])
def user_sessions(user_id: str, db: DbSession, admin: SessionAdmin) -> list[SessionOut]:
    user = user_service.get_visible_user(db, admin, user_id)
    return [SessionOut.model_validate(s) for s in session_service.list_active(db, user.id)]


@router.post("/{user_id}/revoke-sessions", response_model=RevokeResult)
def revoke_user_sessions(
    user_id: str, body: RevokeSessionsRequest, request: Request, db: DbSession, actor: SessionAdmin
) -> RevokeResult:
    user_service.get_managed_user(db, actor, user_id)
    return RevokeResult(revoked=user_service.revoke_sessions(db, audit_context(request, actor), user_id, body.reason))


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, request: Request, db: DbSession, actor: Manager) -> UserOut:
    if actor.institution_id is None:
        raise DomainError("Your account is not assigned to an institution", code="no_institution")
    user = user_service.create_user(
        db, audit_context(request, actor),
        email=body.email, full_name=body.full_name, role=body.role, password=body.password,
        institution_id=actor.institution_id,  # people are created inside the administrator's own institution
    )
    db.commit()
    return UserOut.model_validate(user)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: str, body: UserUpdate, request: Request, db: DbSession, actor: Manager) -> UserOut:
    user_service.get_managed_user(db, actor, user_id)
    user = user_service.update_user(
        db, audit_context(request, actor), user_id,
        full_name=body.full_name, role=body.role, is_active=body.is_active, reason=body.reason,
    )
    return UserOut.model_validate(user)


@router.post("/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def reset_password(user_id: str, body: PasswordReset, request: Request, db: DbSession, actor: Manager) -> None:
    user_service.get_managed_user(db, actor, user_id)
    user_service.reset_password(db, audit_context(request, actor), user_id, body.new_password, body.reason)
