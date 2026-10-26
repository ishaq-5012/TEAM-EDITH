"""Compliance rules, immutable rule versions, synthetic test cases, validation runs and results.

Integrity model:
- A RuleVersion's *content* (definition, effective dates, source, change summary, hash) can change only while
  it is a draft. Once submitted it is frozen; an ORM guard rejects any content change.
- Lifecycle fields (status, reviewer, retirement) change only through the service's allowed transitions.
- ValidationRun and RuleResult rows are immutable: a run stores the exact rule versions (full definitions and
  hashes) and the normalized input snapshot needed to reproduce it.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    inspect,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, TimestampMixin, UTCDateTime, utcnow
from app.models.user import User


class VersionStatus(StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    PUBLISHED = "published"
    REJECTED = "rejected"
    RETIRED = "retired"


STATUS_CHECK = "status IN (" + ", ".join(f"'{s.value}'" for s in VersionStatus) + ")"
OUTCOME_CHECK = "outcome IN ('pass', 'fail', 'review', 'insufficient', 'not_applicable')"


class Rule(IdMixin, TimestampMixin, Base):
    __tablename__ = "rules"

    key: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String(60), nullable=False)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)

    owner: Mapped[User] = relationship(lazy="joined", foreign_keys=[owner_id])
    versions: Mapped[list[RuleVersion]] = relationship(
        back_populates="rule", order_by="RuleVersion.version_number", lazy="selectin"
    )


class RuleVersion(IdMixin, Base):
    __tablename__ = "rule_versions"
    __table_args__ = (
        UniqueConstraint("rule_id", "version_number", name="uq_rule_versions_rule_number"),
        CheckConstraint(STATUS_CHECK, name="status_valid"),
        CheckConstraint("effective_to IS NULL OR effective_to > effective_from", name="effective_window"),
        # At most one open draft and one pending version per rule.
        Index(
            "uq_rule_versions_one_draft",
            "rule_id",
            unique=True,
            sqlite_where=text("status = 'draft'"),
            postgresql_where=text("status = 'draft'"),
        ),
        Index(
            "uq_rule_versions_one_pending",
            "rule_id",
            unique=True,
            sqlite_where=text("status = 'pending_approval'"),
            postgresql_where=text("status = 'pending_approval'"),
        ),
    )

    rule_id: Mapped[str] = mapped_column(ForeignKey("rules.id", ondelete="RESTRICT"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=VersionStatus.DRAFT.value)
    # --- content (frozen once submitted) ---
    definition: Mapped[dict] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)  # exclusive
    source_reference: Mapped[str] = mapped_column(Text, nullable=False, default="")
    change_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # --- lifecycle ---
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    submitted_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    test_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reviewed_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    retired_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    retire_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    rule: Mapped[Rule] = relationship(back_populates="versions", lazy="joined")
    created_by: Mapped[User] = relationship(lazy="joined", foreign_keys=[created_by_id])
    submitted_by: Mapped[User | None] = relationship(lazy="joined", foreign_keys=[submitted_by_id])
    reviewed_by: Mapped[User | None] = relationship(lazy="joined", foreign_keys=[reviewed_by_id])
    retired_by: Mapped[User | None] = relationship(lazy="joined", foreign_keys=[retired_by_id])


CONTENT_FIELDS = (
    "definition",
    "content_hash",
    "effective_from",
    "effective_to",
    "source_reference",
    "change_summary",
    "version_number",
    "rule_id",
)


class ImmutableRuleVersionError(RuntimeError):
    pass


@event.listens_for(RuleVersion, "before_update")
def _freeze_content(_mapper, _conn, target: RuleVersion) -> None:  # noqa: ANN001
    state = inspect(target)
    status_hist = state.attrs.status.history
    previous_status = status_hist.deleted[0] if status_hist.deleted else target.status
    if previous_status == VersionStatus.DRAFT.value:
        return
    changed = [f for f in CONTENT_FIELDS if state.attrs[f].history.has_changes()]
    if changed:
        raise ImmutableRuleVersionError(f"Rule version content is immutable once submitted (attempted: {changed})")


@event.listens_for(RuleVersion, "before_delete")
def _no_delete(*_a) -> None:  # noqa: ANN002
    raise ImmutableRuleVersionError("Rule versions are never deleted")


class RuleTestCase(IdMixin, TimestampMixin, Base):
    """A synthetic input case with the expected outcome. Never real application data."""

    __tablename__ = "rule_test_cases"
    __table_args__ = (CheckConstraint(OUTCOME_CHECK.replace("outcome", "expected_outcome"), name="expected_valid"),)

    rule_id: Mapped[str] = mapped_column(ForeignKey("rules.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    case: Mapped[dict] = mapped_column(JSON, nullable=False)
    expected_outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)


class ValidationRun(IdMixin, Base):
    __tablename__ = "validation_runs"

    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    evaluation_date: Mapped[date] = mapped_column(Date, nullable=False)
    engine_version: Mapped[str] = mapped_column(String(40), nullable=False)
    input_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    # Exact rule versions used: [{rule_id, rule_key, version_id, version_number, content_hash, definition, ...}]
    rule_versions: Mapped[list] = mapped_column(JSON, nullable=False)
    ruleset_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[dict] = mapped_column(JSON, nullable=False)
    # Run lineage: the application's latest run when this one was created, and why this one was created.
    previous_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("validation_runs.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    trigger: Mapped[str] = mapped_column(String(20), nullable=False, default="manual", server_default="manual")
    trigger_data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)

    results: Mapped[list[RuleResult]] = relationship(order_by="RuleResult.position", lazy="selectin")
    created_by: Mapped[User] = relationship(lazy="joined")


class RuleResult(IdMixin, Base):
    __tablename__ = "rule_results"
    __table_args__ = (CheckConstraint(OUTCOME_CHECK, name="outcome_valid"),)

    run_id: Mapped[str] = mapped_column(
        ForeignKey("validation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    rule_id: Mapped[str] = mapped_column(ForeignKey("rules.id", ondelete="RESTRICT"), nullable=False)
    rule_version_id: Mapped[str] = mapped_column(ForeignKey("rule_versions.id", ondelete="RESTRICT"), nullable=False)
    rule_key: Mapped[str] = mapped_column(String(60), nullable=False)
    rule_name: Mapped[str] = mapped_column(String(200), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    reason: Mapped[str] = mapped_column(String(40), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    low_confidence: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    trace: Mapped[list] = mapped_column(JSON, nullable=False)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class ImmutableRunError(RuntimeError):
    pass


for _model in (ValidationRun, RuleResult):

    @event.listens_for(_model, "before_update")
    def _no_update(*_a) -> None:  # noqa: ANN002
        raise ImmutableRunError("Validation runs are immutable")

    @event.listens_for(_model, "before_delete")
    def _no_run_delete(*_a) -> None:  # noqa: ANN002
        raise ImmutableRunError("Validation runs cannot be deleted")
