"""Declarative rule language. Rules are data, never code.

A rule definition is a JSON tree validated by these strict Pydantic models. There is no expression
parser, no ``eval``, no user-supplied regular expressions and no SQL: the only behaviour is the
allowlisted operators below, implemented in ``app.rules.engine``.

Condition grammar
  {"all": [cond, ...]}             every child true
  {"any": [cond, ...]}             at least one child true
  {"not": cond}                    negation
  {"field": REF, "op": OP, "value": V?, "quantifier": "all"|"any"}   leaf comparison

Field references (typed catalog, see ``field_catalog``)
  extracted.<field_key>            values extracted from the application's documents (one per document)
  evidence.<group_key>.outcome     outcome of the current cross-document evidence finding
  application.application_type     string
  application.document_count       number
"""

from __future__ import annotations

import re
from datetime import date
from enum import StrEnum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Discriminator, Field, StringConstraints, Tag, TypeAdapter, model_validator

from app.evidence.config import load_config
from app.extraction.definitions import load_definitions

ENGINE_VERSION = "rules-engine/1.0"
MAX_DEPTH = 6
MAX_LEAVES = 50


class ValueType(StrEnum):
    TEXT = "text"
    DATE = "date"
    NUMBER = "number"
    OUTCOME = "outcome"


OUTCOME_VALUES = ("pass", "fail", "review", "insufficient")

# Operator -> expected `value` shape. Shapes: none | scalar | list | pair | int
OPERATORS: dict[ValueType, dict[str, str]] = {
    ValueType.TEXT: {
        "eq": "scalar",
        "ne": "scalar",
        "in": "list",
        "not_in": "list",
        "contains": "scalar",
        "starts_with": "scalar",
        "ends_with": "scalar",
        "exists": "none",
        "not_exists": "none",
    },
    ValueType.DATE: {
        "eq": "scalar",
        "ne": "scalar",
        "before": "scalar",
        "after": "scalar",
        "on_or_before": "scalar",
        "on_or_after": "scalar",
        "between": "pair",
        "before_evaluation_date": "int",
        "after_evaluation_date": "int",
        "age_years_at_least": "int",
        "age_years_at_most": "int",
        "exists": "none",
        "not_exists": "none",
    },
    ValueType.NUMBER: {
        "eq": "scalar",
        "ne": "scalar",
        "gt": "scalar",
        "gte": "scalar",
        "lt": "scalar",
        "lte": "scalar",
        "between": "pair",
        "exists": "none",
        "not_exists": "none",
    },
    ValueType.OUTCOME: {
        "eq": "scalar",
        "ne": "scalar",
        "in": "list",
        "not_in": "list",
        "exists": "none",
        "not_exists": "none",
    },
}
ALL_OPERATORS = sorted({op for ops in OPERATORS.values() for op in ops})


def field_catalog() -> dict[str, dict[str, Any]]:
    """Every referenceable field with its type and label. Derived from configuration, not hardcoded."""
    definitions, _ = load_definitions()
    comparison, _ = load_config()
    catalog: dict[str, dict[str, Any]] = {}
    for f in definitions.fields:
        catalog[f"extracted.{f.key}"] = {
            "type": ValueType.DATE if f.type.value == "date" else ValueType.TEXT,
            "label": f.label,
            "source": "extracted",
            "multi": True,
            "field_type": f.type.value,
        }
    for g in comparison.groups:
        catalog[f"evidence.{g.key}.outcome"] = {
            "type": ValueType.OUTCOME,
            "label": f"Evidence: {g.label}",
            "source": "evidence",
            "multi": False,
        }
    catalog["application.application_type"] = {
        "type": ValueType.TEXT,
        "label": "Application type",
        "source": "application",
        "multi": False,
    }
    catalog["application.document_count"] = {
        "type": ValueType.NUMBER,
        "label": "Number of documents",
        "source": "application",
        "multi": False,
    }
    return catalog


_STRICT = ConfigDict(extra="forbid", frozen=True)
Scalar = Union[str, int, float]  # noqa: UP007 - pydantic union order matters


class Leaf(BaseModel):
    model_config = _STRICT
    field: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,2}$")]
    op: Literal[tuple(ALL_OPERATORS)]  # type: ignore[valid-type]
    value: Scalar | list[Scalar] | None = None
    quantifier: Literal["all", "any"] = "all"


class AllOf(BaseModel):
    model_config = _STRICT
    all: list[Condition] = Field(min_length=1, max_length=20)


class AnyOf(BaseModel):
    model_config = _STRICT
    any: list[Condition] = Field(min_length=1, max_length=20)


class NotOf(BaseModel):
    model_config = _STRICT
    not_: Condition = Field(alias="not")


def _node_kind(v: Any) -> str | None:
    """Pick the node type from its shape, so validation errors name the right node."""
    if isinstance(v, dict):
        for kind in ("all", "any", "not"):
            if kind in v:
                return kind
        return "leaf"
    return {AllOf: "all", AnyOf: "any", NotOf: "not", Leaf: "leaf"}.get(type(v))


Condition = Annotated[
    Union[  # noqa: UP007
        Annotated[AllOf, Tag("all")],
        Annotated[AnyOf, Tag("any")],
        Annotated[NotOf, Tag("not")],
        Annotated[Leaf, Tag("leaf")],
    ],
    Discriminator(
        _node_kind,
        custom_error_type="invalid_condition",
        custom_error_message="A condition must be a leaf, or an 'all', 'any' or 'not' group",
    ),
]
for _m in (AllOf, AnyOf, NotOf):
    _m.model_rebuild()

Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


class RuleDefinition(BaseModel):
    """The immutable content of a rule version (together with effective dates and source)."""

    model_config = _STRICT

    condition: Condition
    applies_when: Condition | None = None
    severity: Literal["critical", "high", "medium", "low"]
    # What a violated rule produces: a confirmed "fail", or "review" for advisory rules.
    on_violation: Literal["fail", "review"] = "fail"
    # When referenced data is missing (no usable value / no evidence analysis).
    missing_data_policy: Literal["insufficient", "review", "fail", "pass"] = "insufficient"
    # When any input used by the decision has LOW evidence quality.
    low_confidence_policy: Literal["review", "insufficient", "evaluate"] = "review"
    pass_message: Text = ""
    fail_message: Text = ""

    @model_validator(mode="after")
    def _semantics(self) -> RuleDefinition:
        errors = validate_condition(self.condition) + (
            validate_condition(self.applies_when) if self.applies_when else []
        )
        if errors:
            raise ValueError("; ".join(errors))
        return self


def _iter_leaves(node: Any, depth: int = 1):  # noqa: ANN202
    if isinstance(node, Leaf):
        yield node, depth
    elif isinstance(node, AllOf):
        for c in node.all:
            yield from _iter_leaves(c, depth + 1)
    elif isinstance(node, AnyOf):
        for c in node.any:
            yield from _iter_leaves(c, depth + 1)
    elif isinstance(node, NotOf):
        yield from _iter_leaves(node.not_, depth + 1)


def _is_date(v: Any) -> bool:
    if not isinstance(v, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return False
    try:
        date.fromisoformat(v)
    except ValueError:
        return False
    return True


def validate_condition(node: Any) -> list[str]:
    """Type-check every leaf against the field catalog and operator table. Returns error messages."""
    catalog = field_catalog()
    errors: list[str] = []
    leaves = list(_iter_leaves(node))
    if len(leaves) > MAX_LEAVES:
        errors.append(f"too many conditions ({len(leaves)} > {MAX_LEAVES})")
    for leaf, depth in leaves:
        where = f"condition on '{leaf.field}'"
        if depth > MAX_DEPTH:
            errors.append(f"{where}: nesting deeper than {MAX_DEPTH} levels")
        spec = catalog.get(leaf.field)
        if spec is None:
            errors.append(f"{where}: unknown field")
            continue
        vtype: ValueType = spec["type"]
        shape = OPERATORS[vtype].get(leaf.op)
        if shape is None:
            errors.append(f"{where}: operator '{leaf.op}' is not allowed for {vtype.value} fields")
            continue
        v = leaf.value
        if shape == "none" and v is not None:
            errors.append(f"{where}: '{leaf.op}' takes no value")
        elif shape == "int" and (not isinstance(v, int) or isinstance(v, bool) or not -36500 <= v <= 36500):
            errors.append(f"{where}: '{leaf.op}' needs a whole number")
        elif shape == "list" and (not isinstance(v, list) or not 1 <= len(v) <= 100):
            errors.append(f"{where}: '{leaf.op}' needs a list of 1–100 values")
        elif shape == "pair" and (not isinstance(v, list) or len(v) != 2):
            errors.append(f"{where}: '{leaf.op}' needs exactly two values [from, to]")
        elif shape == "scalar" and (v is None or isinstance(v, list)):
            errors.append(f"{where}: '{leaf.op}' needs a single value")
        else:
            items = v if isinstance(v, list) else ([v] if v is not None and shape != "int" else [])
            for item in items:
                if vtype == ValueType.DATE and not _is_date(item):
                    errors.append(f"{where}: '{item}' is not a valid YYYY-MM-DD date")
                elif vtype == ValueType.NUMBER and (not isinstance(item, int | float) or isinstance(item, bool)):
                    errors.append(f"{where}: '{item}' is not a number")
                elif vtype in (ValueType.TEXT, ValueType.OUTCOME) and not isinstance(item, str):
                    errors.append(f"{where}: '{item}' must be text")
                elif vtype == ValueType.OUTCOME and item not in OUTCOME_VALUES:
                    errors.append(f"{where}: '{item}' is not one of {', '.join(OUTCOME_VALUES)}")
                elif isinstance(item, str) and len(item) > 200:
                    errors.append(f"{where}: values must be at most 200 characters")
            if shape == "pair" and not errors and items[0] > items[1]:
                errors.append(f"{where}: range start is after range end")
        if leaf.quantifier == "any" and not spec["multi"]:
            errors.append(f"{where}: 'any' quantifier only applies to extracted fields")
    return errors


_definition_adapter = TypeAdapter(RuleDefinition)


def parse_definition(data: dict) -> RuleDefinition:
    return _definition_adapter.validate_python(data)
