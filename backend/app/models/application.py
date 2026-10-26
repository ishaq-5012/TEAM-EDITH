"""Applications, memberships, documents and processing jobs."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, TimestampMixin, UTCDateTime, utcnow
from app.models.institution import Institution
from app.models.user import User


def _in(column: str, values: type[StrEnum]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v.value}'" for v in values) + ")"


class ApplicationStatus(StrEnum):
    DRAFT = "draft"
    PROCESSING = "processing"
    NEEDS_REVIEW = "needs_review"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class MemberRole(StrEnum):
    CONTRIBUTOR = "contributor"  # may edit and upload
    VIEWER = "viewer"  # read-only


class DocumentStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    NEEDS_REVIEW = "needs_review"  # processed, but a human must look (e.g. no text layer, embedded scripts)
    FAILED = "failed"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Application(IdMixin, TimestampMixin, Base):
    __tablename__ = "applications"
    __table_args__ = (
        CheckConstraint(_in("status", ApplicationStatus), name="status_valid"),
        Index("ix_applications_owner_status", "owner_id", "status"),
    )

    reference: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    applicant_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    application_type: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=ApplicationStatus.DRAFT.value, index=True)
    review_stage: Mapped[str] = mapped_column(String(20), nullable=False, default="reviewer", server_default="reviewer")
    reviewer_completed_by_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reviewer_completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    auditor_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    audited_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    audit_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    # Status to restore when an archived application is reopened.
    status_before_archive: Mapped[str | None] = mapped_column(String(20), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    # Created by the development-only `seed-demo` command. Labelled wherever it appears and filterable in insights.
    is_synthetic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0"), index=True
    )

    institution_id: Mapped[str | None] = mapped_column(
        ForeignKey("institutions.id"), nullable=True, index=True
    )
    institution: Mapped[Institution | None] = relationship(lazy="joined")
    owner: Mapped[User] = relationship(lazy="joined", foreign_keys=[owner_id])
    members: Mapped[list[ApplicationMember]] = relationship(
        back_populates="application", cascade="all, delete-orphan", lazy="selectin"
    )

    def owner_ids(self) -> set[str]:
        """Everyone with any access through ownership or membership (read access)."""
        return {self.owner_id} | {m.user_id for m in self.members}

    def editor_ids(self) -> set[str]:
        return {self.owner_id} | {m.user_id for m in self.members if m.role == MemberRole.CONTRIBUTOR.value}


class ApplicationMember(IdMixin, Base):
    __tablename__ = "application_members"
    __table_args__ = (
        UniqueConstraint("application_id", "user_id", name="uq_application_members_application_user"),
        CheckConstraint(_in("role", MemberRole), name="role_valid"),
    )

    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    added_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)

    application: Mapped[Application] = relationship(back_populates="members")
    user: Mapped[User] = relationship(lazy="joined", foreign_keys=[user_id])


class Document(IdMixin, TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        # The same file (by content hash) may appear only once per application.
        UniqueConstraint("application_id", "sha256", name="uq_documents_application_sha256"),
        CheckConstraint(_in("status", DocumentStatus), name="status_valid"),
    )

    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Display only, sanitised. Never used as a path.
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    document_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # What the client claimed (untrusted, kept for the record) vs what the bytes are.
    declared_mime: Mapped[str | None] = mapped_column(String(120), nullable=True)
    detected_mime: Mapped[str] = mapped_column(String(60), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Random internal name inside private storage. Never returned by the API.
    storage_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=DocumentStatus.QUEUED.value)
    uploaded_by_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)

    application: Mapped[Application] = relationship(lazy="joined")
    uploaded_by: Mapped[User] = relationship(lazy="joined", foreign_keys=[uploaded_by_id])
    jobs: Mapped[list[ProcessingJob]] = relationship(
        back_populates="document", order_by="ProcessingJob.created_at", lazy="selectin"
    )

    @property
    def latest_job(self) -> ProcessingJob | None:
        return self.jobs[-1] if self.jobs else None


class ProcessingJob(IdMixin, Base):
    """One processing attempt for a document. Retries create a new row, so history is preserved."""

    __tablename__ = "processing_jobs"
    __table_args__ = (
        CheckConstraint(_in("status", JobStatus), name="status_valid"),
        # At most one queued/running job per document: concurrent processing is impossible by construction.
        Index(
            "uq_processing_jobs_one_active", "document_id", unique=True,
            sqlite_where=text("status IN ('queued', 'running')"),
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )

    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=JobStatus.QUEUED.value)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # force=True re-runs extraction even when an identical run (same idempotency key) exists.
    force: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requested_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    document: Mapped[Document] = relationship(back_populates="jobs")
