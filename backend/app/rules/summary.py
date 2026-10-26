"""Readable, deterministic summaries of rule definitions and structural version diffs."""

from __future__ import annotations

from typing import Any

from app.rules.schema import AllOf, Leaf, NotOf, RuleDefinition, field_catalog

OP_TEXT = {
    "eq": "is",
    "ne": "is not",
    "in": "is one of",
    "not_in": "is not one of",
    "contains": "contains",
    "starts_with": "starts with",
    "ends_with": "ends with",
    "exists": "is present",
    "not_exists": "is absent",
    "before": "is before",
    "after": "is after",
    "on_or_before": "is on or before",
    "on_or_after": "is on or after",
    "between": "is between",
    "gt": "is greater than",
    "gte": "is at least",
    "lt": "is less than",
    "lte": "is at most",
}


def _value(v: Any) -> str:
    if isinstance(v, list):
        return ", ".join(f"“{x}”" for x in v)
    return f"“{v}”"


def leaf_text(leaf: Leaf, catalog: dict | None = None) -> str:
    catalog = catalog if catalog is not None else field_catalog()
    label = catalog.get(leaf.field, {}).get("label", leaf.field)
    if leaf.field.startswith("extracted."):
        label += " (every document with a value)" if leaf.quantifier == "all" else " (at least one document)"
    op, v = leaf.op, leaf.value
    if op == "before_evaluation_date":
        tail = f"is before the evaluation date{_offset(v)}"
    elif op == "after_evaluation_date":
        tail = f"is after the evaluation date{_offset(v)}"
    elif op == "age_years_at_least":
        tail = f"is at least {v} years before the evaluation date"
    elif op == "age_years_at_most":
        tail = f"is at most {v} years before the evaluation date"
    elif op == "between":
        tail = f"is between “{v[0]}” and “{v[1]}”"
    elif v is None:
        tail = OP_TEXT[op]
    else:
        tail = f"{OP_TEXT[op]} {_value(v)}"
    return f"{label} {tail}"


def _offset(days: int) -> str:
    if not days:
        return ""
    return f" plus {days} days" if days > 0 else f" minus {-days} days"


def condition_text(node: Any, catalog: dict | None = None, indent: int = 0) -> str:
    catalog = catalog if catalog is not None else field_catalog()
    pad = "  " * indent
    if isinstance(node, Leaf):
        return f"{pad}{leaf_text(node, catalog)}"
    if isinstance(node, NotOf):
        return f"{pad}NOT:\n{condition_text(node.not_, catalog, indent + 1)}"
    kind, children = ("ALL of", node.all) if isinstance(node, AllOf) else ("ANY of", node.any)
    return f"{pad}{kind}:\n" + "\n".join(condition_text(c, catalog, indent + 1) for c in children)


def definition_summary(d: RuleDefinition) -> dict[str, str]:
    catalog = field_catalog()
    return {
        "condition": condition_text(d.condition, catalog),
        "applies_when": condition_text(d.applies_when, catalog) if d.applies_when else "Always applies",
        "policies": (
            f"Violation → {d.on_violation}; missing data → {d.missing_data_policy}; "
            f"low-confidence input → {d.low_confidence_policy}; severity {d.severity}."
        ),
    }


def diff(before: Any, after: Any, path: str = "") -> list[dict]:
    """Structural JSON diff: list of {path, change, before, after}."""
    if isinstance(before, dict) and isinstance(after, dict):
        out: list[dict] = []
        for k in sorted(set(before) | set(after)):
            p = f"{path}.{k}" if path else k
            if k not in before:
                out.append({"path": p, "change": "added", "before": None, "after": after[k]})
            elif k not in after:
                out.append({"path": p, "change": "removed", "before": before[k], "after": None})
            else:
                out += diff(before[k], after[k], p)
        return out
    if isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        return [d for i, (b, a) in enumerate(zip(before, after, strict=True)) for d in diff(b, a, f"{path}[{i}]")]
    if before != after:
        return [{"path": path, "change": "changed", "before": before, "after": after}]
    return []
