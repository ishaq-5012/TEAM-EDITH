"""Evidence analyses: findings, field relationships and evidence references.

An EvidenceAnalysis is one reproducible run of the cross-document engine over an application.
Its findings, relationships and evidence references are immutable snapshots: every reference stores
the exact values, page and box that were compared, plus pointers to the extraction run, field and
correction they came from. Later corrections or re-extraction never alter a stored analysis; they
make it *stale* and a new analysis must be run.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, UTCDateTime, utcnow

OUTCOMES = "('pass', 'fail', 'review', 'insufficient')"
QUALITIES = "('high', 'medium', 'low')"


class EvidenceAnalysis(IdMixin, Base):
    __tablename__ = "evidence_analyses"
    __table_args__ = (
        Index(
            "uq_evidence_analyses_one_current",
            "application_id",
            unique=True,
            sqlite_where=text("is_current = 1"),
            postgresql_where=text("is_current"),
        ),
    )

    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    comparator_version: Mapped[str] = mapped_column(String(40), nullable=False)
    config_version: Mapped[str] = mapped_column(String(40), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # sha256 of every input value snapshot + comparator version + config hash. Same fingerprint => same result.
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    document_count: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)

    findings: Mapped[list[EvidenceFinding]] = relationship(order_by="EvidenceFinding.position", lazy="selectin")


class EvidenceFinding(IdMixin, Base):
    __tablename__ = "evidence_findings"
    __table_args__ = (
        CheckConstraint(f"outcome IN {OUTCOMES}", name="outcome_valid"),
        CheckConstraint(f"evidence_quality IS NULL OR evidence_quality IN {QUALITIES}", name="quality_valid"),
        CheckConstraint("severity IN ('critical', 'high', 'medium', 'low')", name="severity_valid"),
        CheckConstraint("priority_score >= 0 AND priority_score <= 100", name="priority_range"),
    )

    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_analyses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    group_key: Mapped[str] = mapped_column(String(60), nullable=False)
    group_label: Mapped[str] = mapped_column(String(120), nullable=False)
    comparator: Mapped[str] = mapped_column(String(30), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    outcome: Mapped[str] = mapped_column(String(15), nullable=False)
    evidence_quality: Mapped[str | None] = mapped_column(String(10), nullable=True)
    priority_score: Mapped[int] = mapped_column(Integer, nullable=False)
    priority_factors: Mapped[list] = mapped_column(JSON, nullable=False)
    coverage: Mapped[dict] = mapped_column(JSON, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)

    references: Mapped[list[EvidenceReference]] = relationship(order_by="EvidenceReference.position", lazy="selectin")
    relationships: Mapped[list[FieldRelationship]] = relationship(
        order_by="FieldRelationship.position", lazy="selectin"
    )


class EvidenceReference(IdMixin, Base):
    """Snapshot of one document's value used by a finding, with provenance pointers."""

    __tablename__ = "evidence_references"
    __table_args__ = (
        UniqueConstraint("finding_id", "document_id", "field_key", name="uq_evidence_references_finding_doc_key"),
    )

    finding_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_findings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    document_name: Mapped[str] = mapped_column(String(255), nullable=False)
    extraction_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="RESTRICT"), nullable=True
    )
    extracted_field_id: Mapped[str | None] = mapped_column(
        ForeignKey("extracted_fields.id", ondelete="RESTRICT"), nullable=True
    )
    correction_id: Mapped[str | None] = mapped_column(
        ForeignKey("field_corrections.id", ondelete="RESTRICT"), nullable=True
    )
    field_key: Mapped[str] = mapped_column(String(60), nullable=False)
    field_label: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    raw_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    effective_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_source: Mapped[str] = mapped_column(String(20), nullable=False)
    method: Mapped[str | None] = mapped_column(String(40), nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox: Mapped[list | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_flags: Mapped[list] = mapped_column(JSON, nullable=False)
    evidence_quality: Mapped[str] = mapped_column(String(10), nullable=False)
    usable: Mapped[bool] = mapped_column(Boolean, nullable=False)


class FieldRelationship(IdMixin, Base):
    """A comparison between two evidence references (source and target fields)."""

    __tablename__ = "field_relationships"
    __table_args__ = (
        CheckConstraint(f"result IN {OUTCOMES}", name="result_valid"),
        CheckConstraint(f"evidence_quality IS NULL OR evidence_quality IN {QUALITIES}", name="quality_valid"),
    )

    finding_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_findings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    source_reference_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_references.id", ondelete="CASCADE"), nullable=False
    )
    target_reference_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_references.id", ondelete="CASCADE"), nullable=False
    )
    result: Mapped[str] = mapped_column(String(15), nullable=False)
    method: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str] = mapped_column(String(60), nullable=False)
    details: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_quality: Mapped[str | None] = mapped_column(String(10), nullable=True)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)


class ImmutableEvidenceError(RuntimeError):
    pass


for _model in (EvidenceFinding, EvidenceReference, FieldRelationship):

    @event.listens_for(_model, "before_update")
    def _no_update(*_a) -> None:  # noqa: ANN002
        raise ImmutableEvidenceError("Stored evidence is immutable; run a new analysis instead")

    @event.listens_for(_model, "before_delete")
    def _no_delete(*_a) -> None:  # noqa: ANN002
        raise ImmutableEvidenceError("Stored evidence cannot be deleted")
