"""Server-side session lifecycle: create, resolve, touch, list, revoke."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from app.core.authz import authorize_owned
from app.core.config import get_settings
from app.core.roles import Permission
from app.core.security import new_token, token_hash
from app.db.base import utcnow
from app.models.session import UserSession
from app.models.user import User
from app.services import audit_service
from app.services.audit_service import AuditContext

# Avoid a DB write on every request: only extend idle expiry when this much time has passed.
TOUCH_INTERVAL = timedelta(seconds=30)


@dataclass(frozen=True)
class IssuedSession:
    session: UserSession
    token: str  # raw value: goes into the HttpOnly cookie, never stored
    csrf_token: str  # raw value: readable cookie + response body


def create(db: Session, user: User, *, ip: str | None, user_agent: str | None) -> IssuedSession:
    settings = get_settings()
    now = utcnow()
    token, csrf = new_token(), new_token()
    session = UserSession(
        user_id=user.id,
        token_hash=token_hash(token),
        csrf_hash=token_hash(csrf),
        created_at=now,
        last_seen_at=now,
        idle_expires_at=now + timedelta(minutes=settings.session_idle_minutes),
        expires_at=now + timedelta(hours=settings.session_absolute_hours),
        ip_address=ip,
        user_agent=(user_agent or "")[:300] or None,
    )
    db.add(session)
    db.flush()
    return IssuedSession(session, token, csrf)


@dataclass(frozen=True)
class Resolution:
    session: UserSession | None
    # "missing" (no such token), "expired", "revoked", "inactive_user" or None when valid.
    problem: str | None


def resolve(db: Session, token: str) -> Resolution:
    session = db.execute(select(UserSession).where(UserSession.token_hash == token_hash(token))).scalar_one_or_none()
    if session is None:
        return Resolution(None, "missing")
    now = utcnow()
    if session.revoked_at is not None:
        return Resolution(session, "revoked")
    if now >= session.idle_expires_at or now >= session.expires_at:
        return Resolution(session, "expired")
    if not session.user.is_active:
        return Resolution(session, "inactive_user")
    return Resolution(session, None)


def touch(db: Session, session: UserSession) -> None:
    """Slide the idle window forward (never past the absolute expiry)."""
    now = utcnow()
    if now - session.last_seen_at < TOUCH_INTERVAL:
        return
    idle = timedelta(minutes=get_settings().session_idle_minutes)
    session.last_seen_at = now
    session.idle_expires_at = min(now + idle, session.expires_at)
    db.commit()


def effective_expiry(session: UserSession) -> datetime:
    return min(session.idle_expires_at, session.expires_at)


def list_active(db: Session, user_id: str) -> list[UserSession]:
    now = utcnow()
    rows = db.execute(
        select(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .order_by(UserSession.last_seen_at.desc())
    ).scalars()
    return [s for s in rows if s.is_valid(now)]


def revoke(db: Session, session: UserSession, reason: str) -> None:
    if session.revoked_at is None:
        session.revoked_at = utcnow()
        session.revoked_reason = reason


def revoke_all_for_user(db: Session, user_id: str, reason: str, *, except_id: str | None = None) -> int:
    stmt = update(UserSession).where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
    if except_id:
        stmt = stmt.where(UserSession.id != except_id)
    result = db.execute(stmt.values(revoked_at=utcnow(), revoked_reason=reason))
    return result.rowcount or 0


def revoke_by_id(db: Session, ctx: AuditContext, actor: User, session_id: str) -> UserSession:
    """Revoke a session the actor owns, or any session if they hold sessions:manage."""
    session = db.get(UserSession, session_id)
    authorize_owned(actor, session, override=Permission.SESSIONS_MANAGE, label="Session")
    assert session is not None
    revoke(db, session, "revoked_by_owner" if session.user_id == actor.id else "revoked_by_admin")
    audit_service.record(
        db, ctx, "auth.session_revoked", entity_type="session", entity_id=session.id,
        summary="Session revoked" + ("" if session.user_id == actor.id else f" for {session.user.email}"),
        data={"session_user_id": session.user_id},
    )
    db.commit()
    return session


def prune_ended(db: Session, ctx: AuditContext, older_than_days: int) -> int:
    """Retention: delete sessions that ended (revoked, idle-expired or past their absolute limit) more than
    ``older_than_days`` ago. Live sessions are never touched. The deletion is recorded in the audit trail."""
    cutoff = utcnow() - timedelta(days=older_than_days)
    # A session ended at the earliest of these; any of them before the cutoff means it ended before the cutoff.
    ended_before_cutoff = or_(
        UserSession.revoked_at < cutoff, UserSession.idle_expires_at < cutoff, UserSession.expires_at < cutoff
    )
    removed = db.execute(delete(UserSession).where(ended_before_cutoff)).rowcount or 0
    audit_service.record(
        db, ctx, "session.retention_pruned", entity_type="user_session",
        summary=f"Deleted {removed} session record(s) that ended more than {older_than_days} days ago",
        data={"removed": removed, "older_than_days": older_than_days},
    )
    db.commit()
    return removed
