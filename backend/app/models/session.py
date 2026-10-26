"""Server-side sessions and login-attempt records."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, UTCDateTime, utcnow
from app.models.user import User


class UserSession(IdMixin, Base):
    """One browser sign-in. Only SHA-256 hashes of the session and CSRF tokens are stored."""

    __tablename__ = "user_sessions"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    csrf_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    idle_expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(String(60), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)

    user: Mapped[User] = relationship(lazy="joined")

    def owner_ids(self) -> set[str]:
        return {self.user_id}

    def is_valid(self, now: datetime) -> bool:
        return self.revoked_at is None and now < self.idle_expires_at and now < self.expires_at


class LoginAttempt(IdMixin, Base):
    """Every sign-in attempt, used for throttling. Not an audit record (audit_events holds those)."""

    __tablename__ = "login_attempts"
    __table_args__ = (
        Index("ix_login_attempts_email_at", "email", "attempted_at"),
        Index("ix_login_attempts_ip_at", "ip_address", "attempted_at"),
    )

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    succeeded: Mapped[bool] = mapped_column(Boolean, nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
