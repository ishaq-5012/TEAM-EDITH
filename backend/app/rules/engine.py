"""Deterministic rule evaluator over a normalized input snapshot.

Logic is three-valued: each condition is TRUE, FALSE or UNKNOWN (data missing), and also carries a
low-confidence marker when any value it used has LOW evidence quality.
  all: any FALSE -> FALSE; else any UNKNOWN -> UNKNOWN; else TRUE
  any: any TRUE  -> TRUE;  else any UNKNOWN -> UNKNOWN; else FALSE
  not: TRUE <-> FALSE, UNKNOWN stays UNKNOWN

Rule outcome (in order):
  applies_when FALSE                         -> not_applicable
  condition (or applies_when) UNKNOWN        -> missing_data_policy  (insufficient | review | fail | pass)
  low-confidence input and policy != evaluate -> review | insufficient
  condition TRUE                             -> pass
  condition FALSE                            -> on_violation (fail | review)

The snapshot carries each field's type, so stored runs re-evaluate identically even if configuration changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from app.rules.schema import AllOf, Leaf, NotOf, RuleDefinition

TRUE, FALSE, UNKNOWN = True, False, None


@dataclass
class Eval:
    value: bool | None
    low: bool = False
    traces: list[dict] = field(default_factory=list)


def _years_between(born: date, on: date) -> int:
    return on.year - born.year - ((on.month, on.day) < (born.month, born.day))


def _check(op: str, actual: Any, expected: Any, vtype: str, evaluation_date: date) -> bool:
    if vtype == "date":
        a = date.fromisoformat(actual)
        if op in ("before_evaluation_date", "after_evaluation_date"):
            pivot = evaluation_date + timedelta(days=int(expected))
            return a < pivot if op == "before_evaluation_date" else a > pivot
        if op == "age_years_at_least":
            return _years_between(a, evaluation_date) >= int(expected)
        if op == "age_years_at_most":
            return _years_between(a, evaluation_date) <= int(expected)
        if op == "between":
            return date.fromisoformat(expected[0]) <= a <= date.fromisoformat(expected[1])
        e = date.fromisoformat(expected)
        return {
            "eq": a == e,
            "ne": a != e,
            "before": a < e,
            "after": a > e,
            "on_or_before": a <= e,
            "on_or_after": a >= e,
        }[op]
    if vtype == "number":
        if op == "between":
            return expected[0] <= actual <= expected[1]
        return {
            "eq": actual == expected,
            "ne": actual != expected,
            "gt": actual > expected,
            "gte": actual >= expected,
            "lt": actual < expected,
            "lte": actual <= expected,
        }[op]
    # text / outcome: exact, case-sensitive comparison of already-normalized values
    if op == "in":
        return actual in expected
    if op == "not_in":
        return actual not in expected
    return {
        "eq": actual == expected,
        "ne": actual != expected,
        "contains": isinstance(actual, str) and str(expected) in actual,
        "starts_with": isinstance(actual, str) and actual.startswith(str(expected)),
        "ends_with": isinstance(actual, str) and actual.endswith(str(expected)),
    }[op]


def _observations(leaf: Leaf, snap: dict) -> tuple[str, list[dict]]:
    """Return (value type, usable observations with provenance) for a field reference."""
    source, *rest = leaf.field.split(".")
    if source == "extracted":
        key = rest[0]
        obs, vtype = [], "text"
        for doc in snap.get("documents", []):
            f = doc.get("fields", {}).get(key)
            if not f:
                continue
            vtype = "date" if f.get("field_type") == "date" else "text"
            usable = f.get("value") is not None and (
                f.get("value_source") == "correction" or f.get("status") in ("found", "ambiguous")
            )
            if usable:
                obs.append(
                    {
                        "kind": "extracted",
                        "document_id": doc.get("document_id"),
                        "document_name": doc.get("name"),
                        "field_key": key,
                        "field_id": f.get("field_id"),
                        "extraction_run_id": f.get("extraction_run_id"),
                        "correction_id": f.get("correction_id"),
                        "value": f["value"],
                        "raw_value": f.get("raw_value"),
                        "value_source": f.get("value_source"),
                        "quality": f.get("quality", "high"),
                        "page_number": f.get("page_number"),
                        "bbox": f.get("bbox"),
                    }
                )
        return vtype, obs
    if source == "evidence":
        ev = snap.get("evidence") or {}
        o = (ev.get("outcomes") or {}).get(rest[0])
        if not o:
            return "outcome", []
        quality = (
            "low" if ev.get("stale") or o.get("evidence_quality") == "low" else (o.get("evidence_quality") or "high")
        )
        return "outcome", [
            {
                "kind": "evidence",
                "analysis_id": ev.get("analysis_id"),
                "finding_id": o.get("finding_id"),
                "group_key": rest[0],
                "value": o["outcome"],
                "quality": quality,
                "stale": bool(ev.get("stale")),
            }
        ]
    attr = rest[0]
    value = (snap.get("application") or {}).get(attr)
    if value is None:
        return ("number" if attr == "document_count" else "text"), []
    return ("number" if attr == "document_count" else "text"), [
        {"kind": "application", "attribute": attr, "value": value, "quality": "high"}
    ]


def _leaf(leaf: Leaf, snap: dict, evaluation_date: date, path: str) -> Eval:
    vtype, obs = _observations(leaf, snap)
    trace = {
        "path": path,
        "field": leaf.field,
        "op": leaf.op,
        "expected": leaf.value,
        "quantifier": leaf.quantifier,
        "value_type": vtype,
    }
    if leaf.op in ("exists", "not_exists"):
        result = bool(obs) if leaf.op == "exists" else not obs
        return Eval(result, False, [{**trace, "result": result, "observations": obs, "low_confidence": False}])
    if not obs:
        return Eval(
            UNKNOWN, False, [{**trace, "result": None, "observations": [], "low_confidence": False, "missing": True}]
        )
    for o in obs:
        o["satisfied"] = _check(leaf.op, o["value"], leaf.value, vtype, evaluation_date)
    results = [o["satisfied"] for o in obs]
    result = all(results) if leaf.quantifier == "all" else any(results)
    low = any(o["quality"] == "low" for o in obs)
    return Eval(result, low, [{**trace, "result": result, "observations": obs, "low_confidence": low}])


def evaluate_condition(node: Any, snap: dict, evaluation_date: date, path: str = "condition") -> Eval:
    if isinstance(node, Leaf):
        return _leaf(node, snap, evaluation_date, path)
    if isinstance(node, NotOf):
        inner = evaluate_condition(node.not_, snap, evaluation_date, f"{path}.not")
        return Eval(None if inner.value is None else not inner.value, inner.low, inner.traces)
    children, name = (node.all, "all") if isinstance(node, AllOf) else (node.any, "any")
    parts = [evaluate_condition(c, snap, evaluation_date, f"{path}.{name}[{i}]") for i, c in enumerate(children)]
    values = [p.value for p in parts]
    if isinstance(node, AllOf):
        value = FALSE if FALSE in values else (UNKNOWN if UNKNOWN in values else TRUE)
    else:
        value = TRUE if TRUE in values else (UNKNOWN if UNKNOWN in values else FALSE)
    return Eval(value, any(p.low for p in parts), [t for p in parts for t in p.traces])


def evaluate(definition: RuleDefinition, snap: dict) -> dict:
    """Evaluate one rule definition. Returns a JSON-serializable result with a full trace."""
    evaluation_date = date.fromisoformat(snap["evaluation_date"])
    traces: list[dict] = []
    if definition.applies_when is not None:
        app = evaluate_condition(definition.applies_when, snap, evaluation_date, "applies_when")
        traces += app.traces
        if app.value is False:
            return {"outcome": "not_applicable", "reason": "not_applicable", "trace": traces, "low_confidence": False}
        if app.value is None:
            return _missing(definition, traces)
    cond = evaluate_condition(definition.condition, snap, evaluation_date)
    traces += cond.traces
    if cond.value is None:
        return _missing(definition, traces)
    if cond.low and definition.low_confidence_policy != "evaluate":
        outcome = "review" if definition.low_confidence_policy == "review" else "insufficient"
        return {
            "outcome": outcome,
            "reason": "low_confidence_input",
            "trace": traces,
            "low_confidence": True,
            "would_have_been": "pass" if cond.value else definition.on_violation,
        }
    if cond.value:
        return {"outcome": "pass", "reason": "condition_met", "trace": traces, "low_confidence": cond.low}
    return {
        "outcome": definition.on_violation,
        "reason": "condition_not_met",
        "trace": traces,
        "low_confidence": cond.low,
    }


def _missing(definition: RuleDefinition, traces: list[dict]) -> dict:
    policy = definition.missing_data_policy
    outcome = definition.on_violation if policy == "fail" else policy
    return {
        "outcome": outcome,
        "reason": "missing_data",
        "trace": traces,
        "low_confidence": False,
        "missing_fields": sorted({t["field"] for t in traces if t.get("missing")}),
    }
