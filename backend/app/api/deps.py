"""Request authentication and authorization dependencies.

Every protected route depends on ``get_current_session`` (directly or through
``CurrentUser`` / ``require_permission``), which:

1. resolves the HttpOnly session cookie to a live server-side session,
2. rejects expired, revoked or deactivated-user sessions with 401 ``session_expired``,
3. enforces the CSRF synchronizer token on every state-changing method,
4. slides the idle-expiry window forward.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.api.cookies import CSRF_HEADER, expiry_header_value
from app.core.config import get_settings
from app.core.errors import DomainError
from app.core.roles import Permission, has_permission
from app.core.security import tokens_match
from app.db.session import get_db
from app.models.session import UserSession
from app.models.user import User
from app.services import audit_service, session_service
from app.services.audit_service import AuditContext

DbSession = Annotated[Session, Depends(get_db)]

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class NotAuthenticated(DomainError):
    status_code = 401
    code = "unauthorized"


class SessionExpired(DomainError):
    status_code = 401
    code = "session_expired"


class CsrfFailed(DomainError):
    status_code = 403
    code = "csrf_failed"


class Forbidden(DomainError):
    status_code = 403
    code = "forbidden"


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def audit_context(request: Request, user: User | None = None) -> AuditContext:
    return AuditContext(
        actor=user,
        request_id=getattr(request.state, "request_id", None),
        ip_address=client_ip(request),
    )


@dataclass(frozen=True)
class AuthContext:
    user: User
    session: UserSession


def get_current_session(request: Request, db: DbSession) -> AuthContext:
    token = request.cookies.get(get_settings().session_cookie_name)
    if not token:
        raise NotAuthenticated("Not authenticated")
    res = session_service.resolve(db, token)
    if res.problem is not None:
        # A cookie was presented but is no longer valid: tell the UI the session ended.
        if res.session is not None and res.problem == "expired" and res.session.revoked_at is None:
            session_service.revoke(db, res.session, "expired")
            db.commit()
        raise SessionExpired("Your session has ended. Please sign in again.")
    session = res.session
    assert session is not None

    if request.method not in SAFE_METHODS:
        supplied = request.headers.get(CSRF_HEADER, "")
        if not supplied or not tokens_match(supplied, session.csrf_hash):
            audit_service.record(
                db, audit_context(request, session.user), "security.csrf_rejected", outcome="failure",
                summary=f"CSRF token {'missing' if not supplied else 'invalid'} on {request.method} {request.url.path}",
                data={"method": request.method, "path": request.url.path},
            )
            db.commit()
            raise CsrfFailed("Missing or invalid CSRF token. Reload the page and try again.")

    session_service.touch(db, session)
    request.state.session_expires = expiry_header_value(session)
    return AuthContext(session.user, session)


CurrentAuth = Annotated[AuthContext, Depends(get_current_session)]


def get_current_user(auth: CurrentAuth) -> User:
    return auth.user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_permission(permission: Permission) -> Callable[..., User]:
    """Role check performed on the server for every request. Denials are audited."""

    def _dep(request: Request, db: DbSession, user: CurrentUser) -> User:
        if not has_permission(user.role, permission):
            audit_service.record(
                db, audit_context(request, user), "security.permission_denied", outcome="failure",
                summary=f"{user.role} lacks {permission.value} for {request.method} {request.url.path}",
                data={"permission": permission.value, "method": request.method, "path": request.url.path},
            )
            db.commit()
            raise Forbidden("You do not have permission to perform this action")
        return user

    return _dep
