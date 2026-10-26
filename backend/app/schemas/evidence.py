from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel

Outcome = Literal["pass", "fail", "review", "insufficient"]
Quality = Literal["high", "medium", "low"]


class EvidenceReferenceOut(ORMModel):
    id: str
    document_id: str
    document_name: str
    extraction_run_id: str | None
    extracted_field_id: str | None
    correction_id: str | None
    field_key: str
    field_label: str
    status: str
    raw_value: str | None
    normalized_value: str | None
    effective_value: str | None
    value_source: Literal["correction", "extracted", "none"]
    method: str | None
    page_number: int | None
    bbox: list[float] | None
    confidence: float | None
    quality_flags: list[str]
    evidence_quality: Quality
    usable: bool
    # Displayed size of `page_number` in the referenced extraction run (same space as `bbox`).
    page_width: float | None = None
    page_height: float | None = None


class RelationshipOut(ORMModel):
    id: str
    source_reference_id: str
    target_reference_id: str
    result: Outcome
    method: str
    reason: str
    details: dict[str, Any]
    evidence_quality: Quality | None
    explanation: str


class PriorityFactor(BaseModel):
    factor: str
    value: Any
    contribution: int
    max: int
    explanation: str


class FindingOut(ORMModel):
    id: str
    group_key: str
    group_label: str
    comparator: str
    severity: Literal["critical", "high", "medium", "low"]
    outcome: Outcome
    evidence_quality: Quality | None
    priority_score: int = Field(description="Deterministic 0–100 ordering aid, not a compliance decision")
    priority_factors: list[PriorityFactor]
    coverage: dict[str, int]
    explanation: str
    references: list[EvidenceReferenceOut]
    relationships: list[RelationshipOut]


class AnalysisMeta(ORMModel):
    id: str
    is_current: bool
    comparator_version: str
    config_version: str
    config_hash: str
    input_fingerprint: str
    document_count: int
    summary: dict[str, int]
    created_at: datetime


class EvidenceView(BaseModel):
    application_id: str
    analysis: AnalysisMeta
    stale: bool = Field(description="Inputs (documents, extractions, corrections, config) changed since this analysis")
    reused: bool = Field(description="True when the request returned an existing analysis with identical inputs")
    can_analyze: bool
    findings: list[FindingOut]


class AnalyzeIn(BaseModel):
    force: bool = False
