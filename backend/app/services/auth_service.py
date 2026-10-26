"""Sign-in with throttling and uniform, non-enumerating failures."""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.core.config import get_settings
from app.core.errors import DomainError
from app.core.security import hash_password, needs_rehash, verify_password
from app.db.base import utcnow
from app.models.session import LoginAttempt, UserSession
from app.services import audit_service, session_service
from app.services.audit_service import AuditContext
from app.services.user_service import get_by_email, normalize_email

INVALID_CREDENTIALS = "Invalid email or password"


class AuthenticationFailed(DomainError):
    status_code = 401
    code = "invalid_credentials"


class LoginThrottled(DomainError):
    status_code = 429
    code = "too_many_attempts"

    def __init__(self, retry_after_seconds: int):
        minutes = max(1, math.ceil(retry_after_seconds / 60))
        super().__init__(f"Too many failed sign-in attempts. Try again in {minutes} minute(s).")
        self.retry_after = retry_after_seconds


def _failures_since(
    db: Session, column: InstrumentedAttribute, value: str, since: datetime
) -> tuple[int, datetime | None]:
    """Failed attempts for this key inside the window, counted after its most recent success.

    Aggregates keep the column's UTCDateTime type, so returned datetimes are timezone-aware.
    """
    last_success = db.execute(
        select(func.max(LoginAttempt.attempted_at)).where(column == value, LoginAttempt.succeeded.is_(True))
    ).scalar_one()
    start = max(since, last_success) if last_success else since
    row = db.execute(
        select(func.count(), func.min(LoginAttempt.attempted_at)).where(
            column == value, LoginAttempt.succeeded.is_(False), LoginAttempt.attempted_at > start
        )
    ).one()
    return row[0], row[1]


def _check_throttle(db: Session, ctx: AuditContext, email: str) -> None:
    settings = get_settings()
    now = utcnow()
    window = timedelta(minutes=settings.login_window_minutes)
    checks = [(LoginAttempt.email, email, settings.login_max_failures, "email")]
    if ctx.ip_address:
        checks.append((LoginAttempt.ip_address, ctx.ip_address, settings.login_ip_max_failures, "ip"))
    for column, value, limit, scope in checks:
        count, oldest = _failures_since(db, column, value, now - window)
        if count >= limit:
            retry = int(((oldest or now) + window - now).total_seconds()) + 1
            audit_service.record(
                db, ctx, "auth.login_throttled", outcome="failure",
                summary=f"Sign-in throttled ({scope} limit)", data={"email": email, "scope": scope},
            )
            db.commit()
            raise LoginThrottled(max(retry, 1))


def _prune(db: Session) -> None:
    db.execute(delete(LoginAttempt).where(LoginAttempt.attempted_at < utcnow() - timedelta(days=1)))


def login(
    db: Session, ctx: AuditContext, email: str, password: str, *, user_agent: str | None
) -> session_service.IssuedSession:
    email = normalize_email(email)
    _check_throttle(db, ctx, email)

    user = get_by_email(db, email)
    ok = verify_password(password, user.password_hash if user else None)
    if not ok or user is None or not user.is_active:
        db.add(LoginAttempt(email=email, ip_address=ctx.ip_address, succeeded=False))
        reason = "unknown_account" if user is None else ("inactive_account" if ok else "wrong_password")
        audit_service.record(
            db, ctx, "auth.login_failed", outcome="failure",
            entity_type="user" if user else None, entity_id=user.id if user else None,
            summary="Sign-in failed", data={"email": email, "reason": reason},
            actor_override=user,
        )
        _prune(db)
        db.commit()
        # Same status and message for every cause: no account enumeration.
        raise AuthenticationFailed(INVALID_CREDENTIALS)

    db.add(LoginAttempt(email=email, ip_address=ctx.ip_address, succeeded=True))
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.last_login_at = utcnow()
    issued = session_service.create(db, user, ip=ctx.ip_address, user_agent=user_agent)
    audit_service.record(
        db, ctx, "auth.login", entity_type="session", entity_id=issued.session.id,
        summary="User signed in", actor_override=user,
    )
    db.commit()
    return issued


def logout(db: Session, ctx: AuditContext, session: UserSession) -> None:
    session_service.revoke(db, session, "logout")
    audit_service.record(db, ctx, "auth.logout", entity_type="session", entity_id=session.id, summary="User signed out")
    db.commit()


def clear_throttle_for(db: Session, email: str) -> None:
    db.execute(delete(LoginAttempt).where(LoginAttempt.email == normalize_email(email)))

