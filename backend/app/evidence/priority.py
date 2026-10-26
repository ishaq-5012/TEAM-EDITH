"""Contradiction impact analysis: a documented, deterministic priority score (0–100).

The score orders the review queue. It is NOT a compliance decision and is never produced by an AI model.
Passing findings are not prioritised (score 0); their factors are still shown.

Factors and their maximum contribution:
  severity          configured for the group      critical 40 · high 30 · medium 20 · low 10
  outcome           finding outcome               fail 30 · review 20 · insufficient 10 · pass 0
  evidence_quality  how solid the evidence is     high 10 · medium 6 · low 2 · none 0
  breadth           documents in disagreement     5 per document beyond the first, max 10
  impact            downstream decisions affected 5 per configured impact, max 10
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.evidence.config import ComparisonGroup

if TYPE_CHECKING:
    from app.evidence.engine import Finding

SEVERITY_POINTS = {"critical": 40, "high": 30, "medium": 20, "low": 10}
OUTCOME_POINTS = {"fail": 30, "review": 20, "insufficient": 10, "pass": 0}
QUALITY_POINTS = {"high": 10, "medium": 6, "low": 2, None: 0}


def priority(group: ComparisonGroup, finding: Finding) -> tuple[int, list[dict]]:
    disputed = {
        d
        for r in finding.relationships
        if r.result in ("fail", "review")
        for d in (r.source.document_id, r.target.document_id)
    }
    breadth = min(10, 5 * max(0, len(disputed) - 1))
    impact = min(10, 5 * len(group.impacts))
    factors = [
        {
            "factor": "severity",
            "value": group.severity.value,
            "contribution": SEVERITY_POINTS[group.severity.value],
            "max": 40,
            "explanation": f"The {group.label.lower()} check is configured as {group.severity.value} severity.",
        },
        {
            "factor": "outcome",
            "value": finding.outcome,
            "contribution": OUTCOME_POINTS[finding.outcome],
            "max": 30,
            "explanation": f"The finding outcome is “{finding.outcome}”.",
        },
        {
            "factor": "evidence_quality",
            "value": finding.evidence_quality,
            "contribution": QUALITY_POINTS[finding.evidence_quality],
            "max": 10,
            "explanation": "Stronger evidence makes the finding more actionable."
            if finding.evidence_quality
            else "No usable values, so there is no evidence to weigh.",
        },
        {
            "factor": "breadth",
            "value": len(disputed),
            "contribution": breadth,
            "max": 10,
            "explanation": f"{len(disputed)} document(s) involved in a disagreement.",
        },
        {
            "factor": "impact",
            "value": list(group.impacts),
            "contribution": impact,
            "max": 10,
            "explanation": ("Affects: " + ", ".join(i.replace("_", " ") for i in group.impacts) + ".")
            if group.impacts
            else "No downstream decisions are configured for this check.",
        },
    ]
    if finding.outcome == "pass":
        return 0, [{**f, "contribution": 0} if f["factor"] != "outcome" else f for f in factors]
    return sum(f["contribution"] for f in factors), factors
