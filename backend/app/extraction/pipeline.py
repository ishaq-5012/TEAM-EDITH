"""Pure extraction pipeline: bytes in, pages + field results out. No database access.

Persisting results, idempotency and concurrency control live in ``app.services.processing``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.extraction import baseline
from app.extraction.baseline import FieldResult
from app.extraction.definitions import FieldDefinitionSet
from app.extraction.ocr import OcrEngine
from app.extraction.pages import PageContent, read_image, read_pdf
from app.models.extraction import FieldStatus, OcrStatus, RunStatus, TextSource

NEEDS_ATTENTION_OCR = {
    OcrStatus.UNAVAILABLE.value,
    OcrStatus.FAILED.value,
    OcrStatus.LOW_CONFIDENCE.value,
    OcrStatus.SKIPPED_LIMIT.value,
}


@dataclass
class ExtractionOutcome:
    pages: list[PageContent]
    fields: list[FieldResult]
    status: str  # RunStatus
    needs_review: bool
    summary: dict


def idempotency_key(input_sha256: str, definitions_hash: str, ocr_engine: str) -> str:
    material = f"{input_sha256}|{baseline.EXTRACTOR}@{baseline.VERSION}|{definitions_hash}|{ocr_engine}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def run(
    data: bytes,
    mime: str,
    document_type: str | None,
    definitions: FieldDefinitionSet,
    engine: OcrEngine,
    max_ocr_pages: int,
) -> ExtractionOutcome:
    pages = (
        read_pdf(data, engine, max_ocr_pages) if mime == "application/pdf" else read_image(data, engine, max_ocr_pages)
    )
    fields = baseline.extract(pages, definitions, document_type)

    unreadable = [p.page_number for p in pages if p.text_source == TextSource.NONE.value]
    attention_pages = [p.page_number for p in pages if p.ocr_status in NEEDS_ATTENTION_OCR]
    counts = {s.value: sum(1 for f in fields if f.status == s.value) for s in FieldStatus}
    problem_fields = [
        f.definition.key
        for f in fields
        if f.status in ("invalid", "ambiguous") or "required_missing" in f.flags or "conflicting_candidates" in f.flags
    ]
    return ExtractionOutcome(
        pages=pages,
        fields=fields,
        status=RunStatus.PARTIAL.value if unreadable else RunStatus.SUCCEEDED.value,
        needs_review=bool(attention_pages or problem_fields),
        summary={
            "pages": len(pages),
            "pages_by_source": {s.value: sum(1 for p in pages if p.text_source == s.value) for s in TextSource},
            "pages_without_text": unreadable,
            "pages_needing_attention": attention_pages,
            "fields": counts,
            "fields_needing_attention": problem_fields,
        },
    )
