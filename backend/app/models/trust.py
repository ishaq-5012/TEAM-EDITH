"""Trust verification runs: an immutable record of what was checked, how, and with what result.

Each run is linked to the document and to the SHA-256 recorded at upload (``recorded_sha256``), and stores the hash
observed at verification time, the configuration used (trust anchors, revocation sources, connectors) and every
check. Runs are append-only (ORM guard and database triggers) so the verification history can't be rewritten.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Index, String, event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, UTCDateTime, utcnow
from app.models.user import User


class TrustVerification(IdMixin, Base):
    __tablename__ = "trust_verifications"
    __table_args__ = (Index("ix_trust_verifications_recorded_sha256", "recorded_sha256"),)

    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    recorded_sha256: Mapped[str] = mapped_column(String(64), nullable=False)  # hash recorded at upload
    observed_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)  # None: file unreadable
    engine_version: Mapped[str] = mapped_column(String(80), nullable=False)
    config: Mapped[dict] = mapped_column(JSON, nullable=False)
    checks: Mapped[list] = mapped_column(JSON, nullable=False)
    signatures: Mapped[list] = mapped_column(JSON, nullable=False)
    summary: Mapped[dict] = mapped_column(JSON, nullable=False)  # dimension -> state; no overall verdict
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)

    created_by: Mapped[User] = relationship(lazy="joined")


class ImmutableVerificationError(RuntimeError):
    pass


@event.listens_for(TrustVerification, "before_update")
def _no_update(*_a) -> None:  # noqa: ANN002
    raise ImmutableVerificationError("Verification records are immutable")


@event.listens_for(TrustVerification, "before_delete")
def _no_delete(*_a) -> None:  # noqa: ANN002
    raise ImmutableVerificationError("Verification records are never deleted")
