from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.extraction import FieldStatus, OcrStatus, RunStatus, TextSource
from app.schemas.application import UserRef
from app.schemas.common import ORMModel


class RunOut(ORMModel):
    id: str
    status: RunStatus
    is_current: bool
    extractor: str
    extractor_version: str
    definitions_hash: str
    ocr_engine: str
    input_sha256: str
    idempotency_key: str
    job_id: str | None
    started_at: datetime
    finished_at: datetime
    summary: dict[str, Any]


class PageOut(ORMModel):
    page_number: int
    width: float
    height: float
    rotation: int
    units: str
    text_source: TextSource
    text_layer_quality: str
    ocr_status: OcrStatus
    ocr_confidence: float | None
    char_count: int
    warnings: list[dict[str, str]]


class PageTextOut(BaseModel):
    page_number: int
    text_source: TextSource
    raw_text: str
    normalized_text: str


class CorrectionOut(ORMModel):
    id: str
    value: str
    normalized_value: str
    reason: str
    based_on_value: str | None
    based_on_field_id: str
    actor: UserRef
    created_at: datetime


class FieldOut(BaseModel):
    id: str
    field_key: str
    field_type: str
    label: str
    status: FieldStatus
    raw_value: str | None
    normalized_value: str | None
    normalized_data: dict[str, Any] | None
    normalization_note: str | None
    method: str | None
    matched_label: str | None
    page_number: int | None
    bbox: list[float] | None = Field(description="[x0, y0, x1, y1] in the displayed page space of `page_number`")
    confidence: float | None = Field(description="Heuristic extraction score 0..1, not a calibrated probability")
    quality_flags: list[str]
    alternatives: list[dict[str, Any]]
    corrections: list[CorrectionOut]
    effective_value: str | None = Field(description="Latest correction if any, else normalized value, else raw value")
    effective_source: str = Field(description="correction | normalized | raw | none")
    correction_based_on_other_value: bool = Field(
        description="The latest correction was made against a different extracted value than this run produced"
    )


class ExtractorInfo(BaseModel):
    name: str
    version: str
    kind: str  # "deterministic_baseline" | "ai"
    limitations: str


class ExtractionView(BaseModel):
    document_id: str
    document_status: str
    detected_mime: str
    run: RunOut
    extractor: ExtractorInfo
    pages: list[PageOut]
    fields: list[FieldOut]
    can_correct: bool
    can_reprocess: bool
    preview_supported: bool


class CorrectionIn(BaseModel):
    value: str = Field(min_length=1, max_length=2000)
    reason: str = Field(min_length=3, max_length=500)


class ReprocessIn(BaseModel):
    force: bool = False
