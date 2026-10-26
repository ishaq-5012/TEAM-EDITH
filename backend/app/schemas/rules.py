from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.schemas.application import UserRef
from app.schemas.common import ORMModel

Key = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{2,59}$")]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)]
Outcome = Literal["pass", "fail", "review", "insufficient", "not_applicable"]


class RuleCreate(BaseModel):
    key: Key
    name: Name
    description: Annotated[str, StringConstraints(max_length=5000)] = ""
    category: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=60)]
    owner_id: str | None = None
    definition: dict[str, Any]
    effective_from: date
    effective_to: date | None = None
    source_reference: Annotated[str, StringConstraints(max_length=2000)] = ""
    change_summary: Annotated[str, StringConstraints(max_length=2000)] = "Initial version"


class RuleMetadataUpdate(BaseModel):
    name: Name | None = None
    description: Annotated[str, StringConstraints(max_length=5000)] | None = None
    category: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=60)] | None = None
    owner_id: str | None = None


class DraftUpdate(BaseModel):
    definition: dict[str, Any] | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    source_reference: Annotated[str, StringConstraints(max_length=2000)] | None = None
    change_summary: Annotated[str, StringConstraints(max_length=2000)] | None = None


class NewVersionIn(BaseModel):
    from_version_id: str | None = None


class ReviewIn(BaseModel):
    note: Note


class RetireIn(BaseModel):
    reason: Note


class DefinitionIn(BaseModel):
    definition: dict[str, Any]


class TestCaseIn(BaseModel):
    name: Name
    description: Annotated[str, StringConstraints(max_length=2000)] = ""
    case: dict[str, Any]
    expected_outcome: Outcome


class TestCaseOut(ORMModel):
    id: str
    name: str
    description: str
    case: dict[str, Any]
    expected_outcome: Outcome
    created_at: datetime


class VersionOut(ORMModel):
    id: str
    version_number: int
    status: Literal["draft", "pending_approval", "published", "rejected", "retired"]
    definition: dict[str, Any]
    content_hash: str
    effective_from: date
    effective_to: date | None
    source_reference: str
    change_summary: str
    created_by: UserRef
    created_at: datetime
    submitted_by: UserRef | None
    submitted_at: datetime | None
    test_summary: dict[str, int] | None
    reviewed_by: UserRef | None
    reviewed_at: datetime | None
    review_note: str | None
    retired_by: UserRef | None
    retired_at: datetime | None
    retire_reason: str | None
    summary: dict[str, str] = Field(default_factory=dict)
    in_force_today: bool = False


class RuleOut(BaseModel):
    id: str
    key: str
    name: str
    description: str
    category: str
    owner: UserRef
    created_at: datetime
    updated_at: datetime
    versions: list[VersionOut]
    test_cases: list[TestCaseOut]
    disclaimer: str


class RuleListItem(BaseModel):
    id: str
    key: str
    name: str
    category: str
    owner: UserRef
    in_force_version: int | None
    in_force_severity: str | None
    latest_version: int
    latest_status: str
    pending_approval: bool
    has_draft: bool


class RuleList(BaseModel):
    items: list[RuleListItem]
    can_manage: bool
    can_publish: bool
    disclaimer: str


class DefinitionCheck(BaseModel):
    valid: bool
    errors: list[dict[str, str]]
    summary: dict[str, str] | None


class TestRun(BaseModel):
    total: int
    passed: int
    failed: int
    results: list[dict[str, Any]]


class ProposalIn(BaseModel):
    rule_id: str
    version_id: str | None = None
    definition: dict[str, Any] | None = None


class SimulateIn(BaseModel):
    application_ids: list[str] = Field(default_factory=list, max_length=50)  # empty: every visible application
    proposals: list[ProposalIn] = Field(min_length=1, max_length=20)
    evaluation_date: date | None = None


class SimulationOut(BaseModel):
    evaluation_date: date
    side_effects: str
    applications: list[dict[str, Any]]


class RuleResultOut(ORMModel):
    id: str
    rule_id: str
    rule_version_id: str
    rule_key: str
    rule_name: str
    version_number: int
    outcome: Outcome
    severity: str
    reason: str
    message: str
    low_confidence: bool
    trace: list[dict[str, Any]]
    details: dict[str, Any]


class ValidationRunOut(ORMModel):
    id: str
    application_id: str
    evaluation_date: date
    engine_version: str
    input_fingerprint: str
    ruleset_fingerprint: str
    summary: dict[str, int]
    created_by: UserRef
    created_at: datetime
    rule_versions: list[dict[str, Any]]
    results: list[RuleResultOut]
    previous_run_id: str | None = None
    trigger: str = "manual"
    trigger_data: dict[str, Any] = Field(default_factory=dict)
    next_run_ids: list[str] = Field(default_factory=list)
    disclaimer: str = ""


class ValidationRunSummary(ORMModel):
    id: str
    evaluation_date: date
    summary: dict[str, int]
    previous_run_id: str | None = None
    trigger: str = "manual"
    created_by: UserRef
    created_at: datetime


class ValidationRunIn(BaseModel):
    evaluation_date: date | None = None
