"""AI interactions: an append-only record of every request that reached an AI provider.

A row stores what was asked (task, subject, prompt version, input fingerprint), what left the environment (the
egress manifest: policy, categories, character count, masking, truncation; never the prompt text itself), what
came back *after validation* (only output that passed the schema, reference and content checks), what was rejected
and why, usage and estimated cost. Rows are never updated or deleted (ORM guard and database triggers), so the
daily budget and the audit trail can't be rewritten.

AI output is advisory. Nothing here is read by the rule engine, trust checks or review decisions.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, CheckConstraint, Float, ForeignKey, Index, Integer, String, event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, UTCDateTime, utcnow
from app.models.user import User


class AITask(StrEnum):
    CLASSIFICATION = "classification"
    FIELD_SUGGESTIONS = "field_suggestions"
    EXPLANATION = "explanation"


class AIStatus(StrEnum):
    SUCCEEDED = "succeeded"  # validated output, nothing dropped
    PARTIAL = "partial"  # validated output, but some items were dropped by the checks
    REJECTED = "rejected"  # the output parsed, but nothing survived the checks
    FAILED = "failed"  # provider error, timeout, refusal, empty or malformed output


def _in(column: str, values: type[StrEnum]) -> str:
    return f"{column} IN ({', '.join(repr(v.value) for v in values)})"


class AIInteraction(IdMixin, Base):
    __tablename__ = "ai_interactions"
    __table_args__ = (
        CheckConstraint(_in("task", AITask), name="task_valid"),
        CheckConstraint(_in("status", AIStatus), name="status_valid"),
        CheckConstraint("cost_usd >= 0", name="cost_non_negative"),
        Index("ix_ai_interactions_subject", "task", "subject_type", "subject_id", "created_at"),
        Index("ix_ai_interactions_created_at", "created_at"),
    )

    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=True)
    task: Mapped[str] = mapped_column(String(30), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(30), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)
    # sha256 over task, prompt version, model, egress policy and the exact request text. Same input => reusable.
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    egress: Mapped[dict] = mapped_column(JSON, nullable=False)
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # validated output only
    validation: Mapped[dict] = mapped_column(JSON, nullable=False)  # dropped items, rejected references, signals
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)

    created_by: Mapped[User] = relationship(lazy="joined")


class ImmutableInteractionError(RuntimeError):
    pass


@event.listens_for(AIInteraction, "before_update")
def _no_update(*_a) -> None:  # noqa: ANN002
    raise ImmutableInteractionError("AI interaction records are immutable")


@event.listens_for(AIInteraction, "before_delete")
def _no_delete(*_a) -> None:  # noqa: ANN002
    raise ImmutableInteractionError("AI interaction records are never deleted")
