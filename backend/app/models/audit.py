"""Append-only, hash-chained audit log.

Each event stores ``prev_hash`` and ``entry_hash = sha256(prev_hash || canonical(event))``.
Updates and deletes are blocked at the ORM layer (below) and by database triggers
created in the migration, so tampering requires bypassing both and is then
detectable by ``audit_service.verify_chain``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Integer, String, Text, event
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, UTCDateTime, utcnow


class AuditEvent(IdMixin, Base):
    __tablename__ = "audit_events"

    seq: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    actor_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False, default="success")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)


class AuditImmutableError(RuntimeError):
    pass


@event.listens_for(AuditEvent, "before_update")
def _block_update(*_args) -> None:  # noqa: ANN002
    raise AuditImmutableError("Audit events are append-only and cannot be modified")


@event.listens_for(AuditEvent, "before_delete")
def _block_delete(*_args) -> None:  # noqa: ANN002
    raise AuditImmutableError("Audit events are append-only and cannot be deleted")


class AuditHead(Base):
    """Single-row chain head: the last sequence number and entry hash.

    Every append starts by UPDATE-ing this row, which takes the database write lock
    (SQLite RESERVED lock / PostgreSQL row lock) *before* the previous hash is read.
    Concurrent appends therefore serialize instead of racing on ``seq``.
    The row is mutable by design; ``verify_chain`` cross-checks it against the events.
    """

    __tablename__ = "audit_head"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    last_hash: Mapped[str] = mapped_column(String(64), nullable=False)
