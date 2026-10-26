"""Cross-document reasoning engine (pure: snapshots in, relationships + findings out).

Outcome rules (in order):
1. A side with no usable value (missing, invalid, document not extracted) -> relationship ``insufficient``.
2. Comparator result ``pass`` with an ``ambiguous`` input (e.g. ambiguous date, not human-confirmed) -> ``review``.
3. Comparator result ``fail`` where either value is LOW quality -> ``review`` (reason ``low_quality_evidence``).
   A confirmed contradiction requires both values to be at least MEDIUM quality.
4. Otherwise the comparator's result stands.

Finding per group: fewer than ``min_values`` usable values -> ``insufficient``; else any ``fail`` -> ``fail``;
any ``review`` -> ``review``; else ``pass``. Values missing from some documents are reported as gaps; they
never turn a finding into a fail.

Evidence quality (independent of outcome and severity), per value:
  high    human correction, or text-layer extraction with no quality flags and score >= 0.8
  medium  OCR without quality flags, or score in [0.6, 0.8)
  low     low OCR confidence, possible OCR confusion, ambiguous value, or score < 0.6
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from itertools import combinations

from app.evidence import comparators
from app.evidence.config import ComparisonConfig, ComparisonGroup
from app.evidence.explain import explain_finding, explain_relationship
from app.evidence.priority import priority

QUALITY_RANK = {"low": 0, "medium": 1, "high": 2}
MAX_VALUES_PER_GROUP = 25  # pairwise comparisons are O(n^2); beyond this, compare against the first value


@dataclass(frozen=True)
class FieldEvidence:
    """Immutable snapshot of one document's value for one field, as used by an analysis."""

    document_id: str
    document_name: str
    extraction_run_id: str | None
    field_id: str | None
    field_key: str
    field_label: str
    status: str  # found | missing | invalid | ambiguous | not_extracted
    raw_value: str | None
    normalized_value: str | None
    effective_value: str | None  # correction if any, else normalized
    value_source: str  # correction | extracted | none
    correction_id: str | None
    method: str | None
    page_number: int | None
    bbox: list[float] | None
    confidence: float | None
    quality_flags: tuple[str, ...]

    @property
    def usable(self) -> bool:
        return self.effective_value is not None and (
            self.value_source == "correction" or self.status in ("found", "ambiguous")
        )

    @property
    def quality(self) -> str:
        if self.value_source == "correction":
            return "high"
        flags = set(self.quality_flags)
        if flags & {"low_ocr_confidence", "possible_ocr_confusion"} or self.status == "ambiguous":
            return "low"
        if self.confidence is not None and self.confidence < 0.6:
            return "low"
        if self.method == "ocr_rule" or (self.confidence is not None and self.confidence < 0.8):
            return "medium"
        return "high"


@dataclass
class Relationship:
    group_key: str
    source: FieldEvidence
    target: FieldEvidence
    result: str  # pass | fail | review | insufficient
    method: str
    reason: str
    details: dict
    evidence_quality: str | None
    explanation: str = ""


@dataclass
class Finding:
    group_key: str
    group_label: str
    comparator: str
    severity: str
    outcome: str
    evidence_quality: str | None
    relationships: list[Relationship]
    values: list[FieldEvidence]
    gaps: list[FieldEvidence]
    coverage: dict
    priority_score: int = 0
    priority_factors: list[dict] = field(default_factory=list)
    explanation: str = ""


def _min_quality(*qualities: str) -> str:
    return min(qualities, key=lambda q: QUALITY_RANK[q])


def _relate(group: ComparisonGroup, a: FieldEvidence, b: FieldEvidence) -> Relationship:
    if not a.usable or not b.usable:
        missing = a if not a.usable else b
        reason = {"missing": "missing_value", "invalid": "invalid_value", "not_extracted": "not_extracted"}.get(
            missing.status, "missing_value"
        )
        # No quality is claimed for a comparison that could not be made.
        return Relationship(
            group.key, a, b, "insufficient", "none", reason, {"missing_side": missing.document_id}, None
        )
    cmp = comparators.compare(group.comparator, a.effective_value, b.effective_value, group.opts())
    quality = _min_quality(a.quality, b.quality)
    result, reason, details = cmp.result, cmp.reason, dict(cmp.details)
    ambiguous_inputs = [x.document_id for x in (a, b) if x.status == "ambiguous" and x.value_source != "correction"]
    if result == "pass" and ambiguous_inputs:
        result, reason = "review", "ambiguous_input"
        details["comparator_result"] = cmp.result
        details["ambiguous_documents"] = ambiguous_inputs
    elif result == "fail" and quality == "low":
        result, reason = "review", "low_quality_evidence"
        details["comparator_result"] = "fail"
        details["comparator_reason"] = cmp.reason
    return Relationship(group.key, a, b, result, cmp.method, reason, details, quality)


def analyze(config: ComparisonConfig, evidence: list[FieldEvidence]) -> list[Finding]:
    """Deterministic: inputs are sorted by the caller (document order); output order follows config order."""
    findings: list[Finding] = []
    for group in config.groups:
        members = [e for e in evidence if e.field_key in group.fields]
        values = [e for e in members if e.usable]
        gaps = [e for e in members if not e.usable]
        relationships: list[Relationship] = []
        if len(values) <= MAX_VALUES_PER_GROUP:
            pairs = list(combinations(values, 2))
        else:
            pairs = [(values[0], v) for v in values[1:]]
        relationships += [_relate(group, a, b) for a, b in pairs]
        # Each gap is linked to the first usable value, so the gap is visible next to real evidence.
        # With no usable value at all there is nothing to compare: the finding lists its gaps and has no edges.
        if values:
            relationships += [_relate(group, values[0], g) for g in gaps]

        compared = [r for r in relationships if r.result != "insufficient"]
        if len(values) < group.min_values:
            outcome = "insufficient"
        elif any(r.result == "fail" for r in compared):
            outcome = "fail"
        elif any(r.result == "review" for r in compared):
            outcome = "review"
        else:
            outcome = "pass"
        quality = _min_quality(*(v.quality for v in values)) if values else None
        finding = Finding(
            group_key=group.key,
            group_label=group.label,
            comparator=group.comparator,
            severity=group.severity.value,
            outcome=outcome,
            evidence_quality=quality,
            relationships=relationships,
            values=values,
            gaps=gaps,
            coverage={
                "documents": len({m.document_id for m in members}),
                "with_value": len(values),
                "missing": sum(1 for g in gaps if g.status == "missing"),
                "invalid": sum(1 for g in gaps if g.status == "invalid"),
                "not_extracted": sum(1 for g in gaps if g.status == "not_extracted"),
                "min_values": group.min_values,
            },
        )
        for r in relationships:
            r.explanation = explain_relationship(group, r)
        finding.priority_score, finding.priority_factors = priority(group, finding)
        finding.explanation = explain_finding(group, finding)
        findings.append(finding)
    return findings


def fingerprint(evidence: list[FieldEvidence], config_hash: str) -> str:
    """Stable hash of every input that can change an analysis result."""
    material = {
        "comparators": comparators.VERSION,
        "config": config_hash,
        "evidence": [asdict(e) for e in evidence],
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True, default=list).encode()).hexdigest()
