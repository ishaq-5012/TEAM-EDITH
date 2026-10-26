"""Review and Resolution Center: review items (cases) and their append-only action history.

A review item is opened for every rule result that is not a pass (fail, review or insufficient). It points
at the immutable rule result that opened it and at the most recent one; rule results, validation runs and
extracted fields are never modified or deleted by review work.

Concurrency: ``version`` is SQLAlchemy's optimistic-lock column. Every mutation must name the version the
client last saw; a mismatch is a 409, and the ORM additionally refuses an UPDATE whose WHERE version no
longer matches (two writers racing between read and write).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint, event, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, UTCDateTime, utcnow
from app.models.user import User


class ReviewStatus(StrEnum):
    OPEN = "open"
    AWAITING_DOCUMENT = "awaiting_document"
    ESCALATED = "escalated"
    CONFIRMED = "confirmed"  # a person agrees the finding stands
    DISMISSED = "dismissed"  # a person decided the finding does not stand (reason required)
    RESOLVED = "resolved"  # a later validation run no longer produced the finding


ACTIVE_STATUSES = (ReviewStatus.OPEN, ReviewStatus.AWAITING_DOCUMENT, ReviewStatus.ESCALATED)
CLOSED_STATUSES = (ReviewStatus.CONFIRMED, ReviewStatus.DISMISSED, ReviewStatus.RESOLVED)


class ReviewCategory(StrEnum):
    FAILURE = "failure"  # rule outcome fail
    UNCERTAIN = "uncertain"  # rule outcome review (low confidence, or the rule routes violations to review)
    MISSING = "missing"  # rule outcome insufficient (required data missing)


CATEGORY_FOR_OUTCOME = {
    "fail": ReviewCategory.FAILURE,
    "review": ReviewCategory.UNCERTAIN,
    "insufficient": ReviewCategory.MISSING,
}


class ReviewActionType(StrEnum):
    OPENED = "opened"
    ASSIGNED = "assigned"
    UNASSIGNED = "unassigned"
    COMMENTED = "commented"
    ESCALATED = "escalated"
    DOCUMENT_REQUESTED = "document_requested"
    RESUMED = "resumed"  # back to open after a document request or escalation
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"
    REOPENED = "reopened"
    FIELD_CORRECTED = "field_corrected"
    REVALIDATED = "revalidated"  # a later validation run updated this item


def _in(column: str, values: type[StrEnum]) -> str:
    return f"{column} IN ({', '.join(repr(v.value) for v in values)})"


_ACTIVE_SQL = "status IN ('open', 'awaiting_document', 'escalated')"


class ReviewItem(IdMixin, Base):
    __tablename__ = "review_items"
    __table_args__ = (
        CheckConstraint(_in("status", ReviewStatus), name="status_valid"),
        CheckConstraint(_in("category", ReviewCategory), name="category_valid"),
        # At most one active item per application and rule; closed items stay as history.
        Index(
            "uq_review_items_active_rule",
            "application_id",
            "rule_id",
            unique=True,
            sqlite_where=text(_ACTIVE_SQL),
            postgresql_where=text(_ACTIVE_SQL),
        ),
        Index("ix_review_items_queue", "status", "category", "priority"),
    )

    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule_id: Mapped[str] = mapped_column(ForeignKey("rules.id", ondelete="RESTRICT"), nullable=False)
    rule_key: Mapped[str] = mapped_column(String(60), nullable=False)
    rule_name: Mapped[str] = mapped_column(String(200), nullable=False)
    origin_result_id: Mapped[str] = mapped_column(ForeignKey("rule_results.id", ondelete="RESTRICT"), nullable=False)
    current_result_id: Mapped[str] = mapped_column(ForeignKey("rule_results.id", ondelete="RESTRICT"), nullable=False)
    current_run_id: Mapped[str] = mapped_column(ForeignKey("validation_runs.id", ondelete="RESTRICT"), nullable=False)
    previous_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("review_items.id", ondelete="RESTRICT"), nullable=True
    )
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)  # outcome of the current result
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)  # documented in review_service.priority_for
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=ReviewStatus.OPEN.value)
    assignee_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    document_request: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # the open request, if any
    closed_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False)

    assignee: Mapped[User | None] = relationship(lazy="joined", foreign_keys=[assignee_id])
    closed_by: Mapped[User | None] = relationship(lazy="joined", foreign_keys=[closed_by_id])
    actions: Mapped[list[ReviewAction]] = relationship(order_by="ReviewAction.sequence", lazy="selectin")

    __mapper_args__ = {"version_id_col": version}

    @property
    def is_active(self) -> bool:
        return self.status in {s.value for s in ACTIVE_STATUSES}


class ReviewAction(IdMixin, Base):
    """One immutable entry in an item's history. Never updated or deleted (ORM guard and DB triggers)."""

    __tablename__ = "review_actions"
    __table_args__ = (
        CheckConstraint(_in("action", ReviewActionType), name="action_valid"),
        UniqueConstraint("item_id", "sequence", name="uq_review_actions_item_sequence"),
        # Idempotency: a client-supplied request id can be used once per item (NULLs are not compared).
        UniqueConstraint("item_id", "request_id", name="uq_review_actions_item_request"),
    )

    item_id: Mapped[str] = mapped_column(ForeignKey("review_items.id", ondelete="RESTRICT"), nullable=False, index=True)
    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)

    actor: Mapped[User] = relationship(lazy="joined")


class ImmutableReviewActionError(RuntimeError):
    pass


@event.listens_for(ReviewAction, "before_update")
def _no_update(*_a) -> None:  # noqa: ANN002
    raise ImmutableReviewActionError("Review history is append-only")


@event.listens_for(ReviewAction, "before_delete")
def _no_delete(*_a) -> None:  # noqa: ANN002
    raise ImmutableReviewActionError("Review history is append-only")


@event.listens_for(ReviewItem, "before_delete")
def _no_item_delete(*_a) -> None:  # noqa: ANN002
    raise ImmutableReviewActionError("Review items are never deleted; they are closed with a recorded decision")
