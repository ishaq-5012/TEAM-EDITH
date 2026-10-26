from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class HealthOut(BaseModel):
    state: Literal["unknown", "healthy", "degraded", "failing"]
    calls: int
    failures: int
    consecutive_failures: int
    last_success_at: str | None
    last_error_at: str | None
    last_error_code: str | None
    last_check_at: str | None
    last_check_ok: bool | None
    last_check_detail: str | None


class ProviderStateOut(BaseModel):
    name: str
    configured_name: str
    enabled: bool
    configured: bool
    model: str | None
    detail: str
    health: HealthOut


class TaskAvailabilityOut(BaseModel):
    key: str
    label: str
    available: bool
    reason: str


class EgressPolicyOut(BaseModel):
    policy: Literal["none", "extracted_values", "page_text"]
    description: str
    mask_identifiers: bool
    max_input_chars: int


class LimitsOut(BaseModel):
    timeout_seconds: float
    max_retries: int
    max_output_tokens: int
    rate_limit_per_minute: int
    user_rate_limit_per_hour: int


class BudgetOut(BaseModel):
    daily_usd: float
    spent_today_usd: float
    remaining_usd: float
    input_usd_per_mtok: float
    output_usd_per_mtok: float


class StatusOut(BaseModel):
    provider: ProviderStateOut
    egress: EgressPolicyOut
    limits: LimitsOut
    budget: BudgetOut
    tasks: list[TaskAvailabilityOut]
    limitations: list[str]


class CheckOut(BaseModel):
    ok: bool
    detail: str
    error_code: str | None
    provider: ProviderStateOut


class ErrorOut(BaseModel):
    code: str
    message: str


class ActorOut(BaseModel):
    id: str
    full_name: str


class UsageOut(BaseModel):
    input_tokens: int
    output_tokens: int
    cost_usd: float
    attempts: int
    duration_ms: int


class InteractionOut(BaseModel):
    interaction_id: str
    status: Literal["succeeded", "partial", "rejected", "failed"]
    error: ErrorOut | None
    # Validated output only; its shape depends on the task (see docs/API.md).
    output: dict[str, Any] | None
    validation: dict[str, Any]
    provider: str
    model: str | None
    prompt_version: str
    created_at: datetime
    created_by: ActorOut
    cached: bool
    stale: bool
    egress: dict[str, Any]
    usage: UsageOut


class EvidenceLinkOut(BaseModel):
    id: str
    kind: str
    label: str
    link: dict[str, Any] | None


class StatementOut(BaseModel):
    text: str
    references: list[EvidenceLinkOut]


class FallbackOut(BaseModel):
    statements: list[StatementOut]


class SubjectOut(BaseModel):
    type: Literal["review_item", "evidence_finding", "application"]
    id: str
    application_id: str
    application_reference: str


class ExplanationOut(BaseModel):
    subject: SubjectOut
    # The deterministic result. Authoritative; AI output never changes it.
    deterministic: dict[str, Any]
    fallback: FallbackOut
    ai: InteractionOut | None
    error: ErrorOut | None
    provider: ProviderStateOut
    can_request: bool
    limitations: list[str]


class ExplanationIn(BaseModel):
    subject_type: Literal["review_item", "evidence_finding", "application"]
    subject_id: str = Field(min_length=1, max_length=32)
    refresh: bool = False  # bypass the stored answer for identical input


class DocumentAssistIn(BaseModel):
    refresh: bool = False


class DocumentFallbackOut(BaseModel):
    document_type: str | None
    document_type_source: str | None
    fields: str


class DocumentAssistOut(BaseModel):
    application_id: str
    document_id: str
    document_name: str
    fallback: DocumentFallbackOut
    provider: ProviderStateOut
    can_request: bool
    egress_allows_page_text: bool
    tasks: list[TaskAvailabilityOut]
    limitations: list[str]
    classification: InteractionOut | None
    classification_error: ErrorOut | None
    field_suggestions: InteractionOut | None
    field_suggestions_error: ErrorOut | None
