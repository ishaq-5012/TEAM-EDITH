"""Stable identity and version mapping for the institution portal transport."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin


class PortalSubmission(IdMixin, TimestampMixin, Base):
    __tablename__ = "portal_submissions"
    __table_args__ = (UniqueConstraint("portal_application_id", "version"),)

    portal_application_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id", ondelete="RESTRICT"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    expected_documents: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="receiving")
    validation_state: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    validation_run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    validation_error: Mapped[str | None] = mapped_column(String(200), nullable=True)


class PortalDocument(IdMixin, TimestampMixin, Base):
    __tablename__ = "portal_documents"
    __table_args__ = (UniqueConstraint("submission_id", "portal_version_id"),)

    submission_id: Mapped[str] = mapped_column(ForeignKey("portal_submissions.id", ondelete="RESTRICT"), nullable=False)
    portal_version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    portal_document_id: Mapped[str] = mapped_column(String(64), nullable=False)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False)
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
