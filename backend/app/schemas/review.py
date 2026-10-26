from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.schemas.application import UserRef
from app.schemas.common import ORMModel
from app.schemas.evidence import FindingOut

Status = Literal["open", "awaiting_document", "escalated", "confirmed", "dismissed", "resolved"]
Category = Literal["failure", "uncertain", "missing"]
RequestId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{8,64}$")]
Reason = Annotated[str, StringConstraints(max_length=2000)]

SubmittableAction = Literal[
    "assigned",
    "unassigned",
    "commented",
    "escalated",
    "document_requested",
    "resumed",
    "confirmed",
    "dismissed",
    "reopened",
]


class ActionIn(BaseModel):
    action: SubmittableAction
    expected_version: int = Field(ge=1, description="The item version the client last saw (optimistic locking)")
    request_id: RequestId | None = Field(default=None, description="Idempotency key; retries return the first result")
    reason: Reason | None = None
    assignee_id: str | None = None
    document_description: Annotated[str, StringConstraints(max_length=500)] | None = None


class CorrectionIn(BaseModel):
    expected_version: int = Field(ge=1)
    request_id: RequestId | None = None
    document_id: str
    field_id: str
    value: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    reason: Reason


class AppRef(ORMModel):
    id: str
    reference: str
    title: str
    status: str


class ReviewActionOut(ORMModel):
    id: str
    sequence: int
    action: str
    actor: UserRef
    from_status: str | None
    to_status: str | None
    reason: str | None
    data: dict[str, Any]
    request_id: str | None
    created_at: datetime


class ReviewItemOut(ORMModel):
    id: str
    application_id: str
    rule_id: str
    rule_key: str
    rule_name: str
    origin_result_id: str
    current_result_id: str
    current_run_id: str
    previous_item_id: str | None
    category: Category
    outcome: str
    severity: str
    priority: int
    status: Status
    assignee: UserRef | None
    document_request: dict[str, Any] | None
    closed_by: UserRef | None
    closed_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime


class QueueRow(BaseModel):
    item: ReviewItemOut
    application: AppRef


class QueueOut(BaseModel):
    items: list[QueueRow]
    total: int
    limit: int
    offset: int
    counts: dict[str, Any]
    can_act_anywhere: bool


class ActionOut(BaseModel):
    item: ReviewItemOut
    action: ReviewActionOut
    replayed: bool
    revalidation: dict[str, Any] | None = None


class RunRef(ORMModel):
    id: str
    evaluation_date: date
    created_at: datetime
    trigger: str
    previous_run_id: str | None


class ResultOut(ORMModel):
    id: str
    rule_version_id: str
    version_number: int
    outcome: str
    severity: str
    reason: str
    message: str
    low_confidence: bool
    trace: list[dict[str, Any]]
    details: dict[str, Any]


class PreviousItem(ORMModel):
    id: str
    status: Status
    outcome: str
    created_at: datetime
    closed_at: datetime | None


class ReviewDetail(BaseModel):
    item: ReviewItemOut
    application: AppRef
    result: ResultOut
    run: RunRef
    rule: dict[str, Any]
    uncertainty: list[dict[str, Any]]
    fields: list[dict[str, Any]]
    evidence: dict[str, Any]
    history: list[ReviewActionOut]
    previous_items: list[PreviousItem]
    rule_runs: list[dict[str, Any]]
    permissions: dict[str, bool]


class EvidenceOut(BaseModel):
    analysis_id: str | None
    findings: list[FindingOut]
