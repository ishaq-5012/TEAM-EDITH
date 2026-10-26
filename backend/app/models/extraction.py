"""Extraction runs, per-page text, extracted fields and human corrections.

Integrity model:
- ExtractionRun rows are kept forever. ``is_current`` marks the run shown by default; a partial
  unique index guarantees at most one current run per document.
- DocumentPage and ExtractedField rows are written once, in the same transaction that completes
  their run, and never updated (ORM guards below). Original extracted values therefore cannot be
  altered by later corrections or re-processing.
- FieldCorrection rows are append-only. They are keyed by (document, field_key) so they survive
  re-processing, and record the extracted value they were made against.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

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
from app.models.user import User


def _in(column: str, values: type[StrEnum]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v.value}'" for v in values) + ")"


class RunStatus(StrEnum):
    SUCCEEDED = "succeeded"  # every page produced usable text (or did not need it)
    PARTIAL = "partial"  # some pages had no usable text (OCR unavailable/failed/low quality)


class TextSource(StrEnum):
    TEXT_LAYER = "text_layer"
    OCR = "ocr"
    NONE = "none"


class OcrStatus(StrEnum):
    NOT_NEEDED = "not_needed"
    COMPLETED = "completed"
    LOW_CONFIDENCE = "low_confidence"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"
    SKIPPED_LIMIT = "skipped_limit"


class FieldStatus(StrEnum):
    FOUND = "found"
    MISSING = "missing"
    INVALID = "invalid"
    AMBIGUOUS = "ambiguous"


class ExtractionRun(IdMixin, Base):
    __tablename__ = "extraction_runs"
    __table_args__ = (
        CheckConstraint(_in("status", RunStatus), name="status_valid"),
        Index(
            "uq_extraction_runs_one_current",
            "document_id",
            unique=True,
            sqlite_where=text("is_current = 1"),
            postgresql_where=text("is_current"),
        ),
        Index("ix_extraction_runs_idempotency", "document_id", "idempotency_key"),
    )

    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("processing_jobs.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    extractor: Mapped[str] = mapped_column(String(60), nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(20), nullable=False)
    definitions_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ocr_engine: Mapped[str] = mapped_column(String(80), nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # sha256(input_sha256 | extractor@version | definitions_hash | ocr_engine): same key => same output.
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    pages: Mapped[list[DocumentPage]] = relationship(order_by="DocumentPage.page_number", lazy="selectin")
    fields: Mapped[list[ExtractedField]] = relationship(order_by="ExtractedField.position", lazy="selectin")


class DocumentPage(IdMixin, Base):
    __tablename__ = "document_pages"
    __table_args__ = (
        UniqueConstraint("run_id", "page_number", name="uq_document_pages_run_page"),
        CheckConstraint(_in("text_source", TextSource), name="text_source_valid"),
        CheckConstraint(_in("ocr_status", OcrStatus), name="ocr_status_valid"),
    )

    run_id: Mapped[str] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-based
    # Displayed page size (rotation applied): PDF points for PDFs, pixels for images.
    width: Mapped[float] = mapped_column(Float, nullable=False)
    height: Mapped[float] = mapped_column(Float, nullable=False)
    rotation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    units: Mapped[str] = mapped_column(String(10), nullable=False)  # "pt" | "px"
    text_source: Mapped[str] = mapped_column(String(20), nullable=False)
    text_layer_quality: Mapped[str] = mapped_column(String(20), nullable=False)  # good|sparse|unusable|none|n/a
    ocr_status: Mapped[str] = mapped_column(String(20), nullable=False)
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)  # mean word confidence 0..100
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)  # exactly as produced by the source
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)  # whitespace-normalized copy
    warnings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)


class ExtractedField(IdMixin, Base):
    __tablename__ = "extracted_fields"
    __table_args__ = (
        UniqueConstraint("run_id", "field_key", name="uq_extracted_fields_run_key"),
        CheckConstraint(_in("status", FieldStatus), name="status_valid"),
    )

    run_id: Mapped[str] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)  # order from the field definitions
    field_key: Mapped[str] = mapped_column(String(60), nullable=False)
    field_type: Mapped[str] = mapped_column(String(30), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    raw_value: Mapped[str | None] = mapped_column(Text, nullable=True)  # characters as found in the source
    normalized_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # strict schema dump
    normalization_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    method: Mapped[str | None] = mapped_column(String(40), nullable=True)
    matched_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox: Mapped[list | None] = mapped_column(JSON, nullable=True)  # [x0, y0, x1, y1] in displayed page space
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)  # heuristic score 0..1
    quality_flags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    alternatives: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class FieldCorrection(IdMixin, Base):
    __tablename__ = "field_corrections"
    __table_args__ = (Index("ix_field_corrections_document_key", "document_id", "field_key"),)

    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    field_key: Mapped[str] = mapped_column(String(60), nullable=False)
    based_on_field_id: Mapped[str] = mapped_column(
        ForeignKey("extracted_fields.id", ondelete="RESTRICT"), nullable=False
    )
    based_on_value: Mapped[str | None] = mapped_column(Text, nullable=True)  # extracted value at the time
    value: Mapped[str] = mapped_column(Text, nullable=False)  # as entered by the person
    normalized_value: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)

    actor: Mapped[User] = relationship(lazy="joined")


class ImmutableRecordError(RuntimeError):
    pass


def _immutable(model: type, what: str) -> None:
    @event.listens_for(model, "before_update")
    def _no_update(*_a) -> None:  # noqa: ANN002
        raise ImmutableRecordError(f"{what} are immutable once written")

    @event.listens_for(model, "before_delete")
    def _no_delete(*_a) -> None:  # noqa: ANN002
        raise ImmutableRecordError(f"{what} cannot be deleted")


_immutable(DocumentPage, "Extracted pages")
_immutable(ExtractedField, "Extracted fields")
_immutable(FieldCorrection, "Field corrections")
