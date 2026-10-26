"""Explanations generated from stored structured evidence only (templates, no AI, no external text).

Every value, document name and page number in an explanation comes from the FieldEvidence snapshots and
comparison details of the relationship being explained.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.evidence.config import ComparisonGroup

if TYPE_CHECKING:
    from app.evidence.engine import FieldEvidence, Finding, Relationship

REASONS = {
    "equal": "The values are identical.",
    "equal_after_normalization": "The values are equal after the approved normalizations: {normalizations}.",
    "equal_after_token_reorder": "The values contain the same words in a different order (reordering is allowed for this check).",
    "within_tolerance": "The dates differ by {difference_days} day(s), within the configured tolerance of {tolerance_days}.",
    "different_values": "The values differ.",
    "near_match": "The values differ by {edit_distance} character(s). This may be a typo or a recognition error, so a person must decide.",
    "token_order_differs": "The values contain the same words in a different order; reordering is not approved for this check.",
    "possible_initials": "The values share {shared_tokens} but differ elsewhere, possibly an initial. Not treated as equal.",
    "partial_token_match": "The values share {shared_tokens} but differ in {differing_tokens}. No alias is assumed.",
    "possible_day_month_swap": "The dates match if day and month are swapped; the source format may be ambiguous.",
    "possible_ocr_confusion": "The values differ only in characters OCR commonly confuses (positions {differing_positions}).",
    "separators_differ": "The values differ only in separators, and ignoring separators is not configured for this check.",
    "partial_address_match": "The addresses overlap ({token_overlap:.0%} of words) but differ in {differing_tokens}.",
    "ambiguous_input": "The values match, but at least one value was ambiguous when extracted and has not been confirmed.",
    "low_quality_evidence": "The values appear to differ, but at least one was read with low confidence, so this is not treated as a confirmed contradiction.",
    "missing_value": "No value was found in one of the documents, so they cannot be compared.",
    "invalid_value": "The value in one document is not valid for this field, so they cannot be compared.",
    "not_extracted": "One of the documents has not been extracted yet.",
}

RESULT_TEXT = {
    "pass": "Consistent",
    "fail": "Contradiction",
    "review": "Review required",
    "insufficient": "Insufficient evidence",
}


def describe_value(e: FieldEvidence) -> str:
    where = f"“{e.document_name}”"
    if e.page_number:
        where += f" (page {e.page_number})"
    if e.effective_value is None:
        return f"{where}: no value ({e.status.replace('_', ' ')})"
    shown = e.effective_value.replace("\n", ", ")
    suffix = " — human-corrected" if e.value_source == "correction" else ""
    return f"{where}: “{shown}”{suffix}"


def _format(template: str, details: dict) -> str:
    safe = {k: (", ".join(map(str, v)) if isinstance(v, list) else v) for k, v in details.items()}
    try:
        return template.format(**safe)
    except (KeyError, ValueError):
        return template.split("{")[0].strip()


def explain_relationship(group: ComparisonGroup, r: Relationship) -> str:
    reason = _format(REASONS.get(r.reason, r.reason), r.details)
    return (
        f"{RESULT_TEXT[r.result]} — {group.label}: {describe_value(r.source)} vs {describe_value(r.target)}. "
        f"{reason}" + (f" Evidence quality: {r.evidence_quality}." if r.evidence_quality else "")
    )


def explain_finding(group: ComparisonGroup, f: Finding) -> str:
    counts = {k: sum(1 for r in f.relationships if r.result == k) for k in ("pass", "fail", "review", "insufficient")}
    parts = [f"{group.label}: {RESULT_TEXT[f.outcome].lower()}."]
    if f.outcome == "insufficient":
        parts.append(
            f"{f.coverage['with_value']} usable value(s) found; at least {f.coverage['min_values']} are needed to compare."
        )
    else:
        parts.append(
            f"{f.coverage['with_value']} document(s) provide a value; {counts['pass']} pair(s) consistent, "
            f"{counts['fail']} contradicting, {counts['review']} needing review."
        )
    if f.gaps:
        parts.append("No usable value in: " + "; ".join(describe_value(g) for g in f.gaps) + ".")
    parts.append(f"Severity {f.severity}; evidence quality {f.evidence_quality or 'none'}.")
    return " ".join(parts)
