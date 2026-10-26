"""Rule language: every operator, three-valued logic, policies, date boundaries and schema rejection."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.rules.engine import evaluate
from app.rules.schema import OPERATORS, ValueType, parse_definition
from app.rules.summary import definition_summary

EVAL_DATE = "2026-10-23"


def snap(
    fields: dict | None = None,
    *,
    evidence: dict | None = None,
    app_type: str = "kyc",
    docs: int = 1,
    stale: bool = False,
    extra_docs: list[dict] | None = None,
) -> dict:
    types = {"date_of_birth": "date", "expiry_date": "date", "issue_date": "date"}
    documents = [
        {
            "document_id": "d1",
            "name": "synthetic-1.pdf",
            "fields": {
                k: {
                    "value": v if not isinstance(v, dict) else v.get("value"),
                    "status": (v.get("status", "found") if isinstance(v, dict) else "found"),
                    "quality": (v.get("quality", "high") if isinstance(v, dict) else "high"),
                    "value_source": "extracted",
                    "field_type": types.get(k, "name"),
                    "field_id": f"f-{k}",
                    "page_number": 1,
                    "bbox": [1, 2, 3, 4],
                }
                for k, v in (fields or {}).items()
            },
        }
    ]
    documents += extra_docs or []
    return {
        "evaluation_date": EVAL_DATE,
        "application": {"application_type": app_type, "document_count": docs},
        "documents": documents,
        "evidence": None
        if evidence is None
        else {
            "analysis_id": "an",
            "stale": stale,
            "outcomes": {
                k: {"outcome": v, "finding_id": f"fi-{k}", "evidence_quality": "high"} for k, v in evidence.items()
            },
        },
    }


def rule(condition: dict, **kw) -> object:
    return parse_definition({"condition": condition, "severity": "high", **kw})


def outcome(condition: dict, s: dict, **kw) -> str:
    return evaluate(rule(condition, **kw), s)["outcome"]


# ------------------------------------------------------------------ every operator


TEXT = [
    ("eq", "Test Person", "Test Person", True),
    ("eq", "Test Person", "Other", False),
    ("ne", "Other", "Test Person", True),
    ("ne", "Test Person", "Test Person", False),
    ("in", ["A", "Test Person"], "Test Person", True),
    ("in", ["A", "B"], "Test Person", False),
    ("not_in", ["A", "B"], "Test Person", True),
    ("not_in", ["Test Person"], "Test Person", False),
    ("contains", "Pers", "Test Person", True),
    ("contains", "xyz", "Test Person", False),
    ("starts_with", "Test", "Test Person", True),
    ("starts_with", "Person", "Test Person", False),
    ("ends_with", "Person", "Test Person", True),
    ("ends_with", "Test", "Test Person", False),
]


@pytest.mark.parametrize("op,value,actual,expected", TEXT)
def test_text_operators(op, value, actual, expected):
    got = outcome({"field": "extracted.full_name", "op": op, "value": value}, snap({"full_name": actual}))
    assert got == ("pass" if expected else "fail")


DATES = [
    ("eq", "1990-03-03", True),
    ("eq", "1990-03-04", False),
    ("ne", "1990-03-04", True),
    ("ne", "1990-03-03", False),
    ("before", "1990-03-04", True),
    ("before", "1990-03-03", False),
    ("after", "1990-03-02", True),
    ("after", "1990-03-03", False),
    ("on_or_before", "1990-03-03", True),
    ("on_or_before", "1990-03-02", False),
    ("on_or_after", "1990-03-03", True),
    ("on_or_after", "1990-03-04", False),
    ("between", ["1990-01-01", "1990-12-31"], True),
    ("between", ["1991-01-01", "1991-12-31"], False),
    ("before_evaluation_date", 0, True),
    ("after_evaluation_date", 0, False),
    ("age_years_at_least", 36, True),
    ("age_years_at_least", 37, False),
    ("age_years_at_most", 36, True),
    ("age_years_at_most", 35, False),
]


@pytest.mark.parametrize("op,value,expected", DATES)
def test_date_operators(op, value, expected):
    got = outcome({"field": "extracted.date_of_birth", "op": op, "value": value}, snap({"date_of_birth": "1990-03-03"}))
    assert got == ("pass" if expected else "fail")


NUMBERS = [
    ("eq", 2, True),
    ("ne", 2, False),
    ("gt", 1, True),
    ("gt", 2, False),
    ("gte", 2, True),
    ("gte", 3, False),
    ("lt", 3, True),
    ("lt", 2, False),
    ("lte", 2, True),
    ("lte", 1, False),
    ("between", [1, 2], True),
    ("between", [3, 5], False),
]


@pytest.mark.parametrize("op,value,expected", NUMBERS)
def test_number_operators(op, value, expected):
    got = outcome({"field": "application.document_count", "op": op, "value": value}, snap(docs=2))
    assert got == ("pass" if expected else "fail")


@pytest.mark.parametrize(
    "op,value,expected",
    [("eq", "pass", True), ("ne", "pass", False), ("in", ["review", "pass"], True), ("not_in", ["pass"], False)],
)
def test_outcome_operators(op, value, expected):
    got = outcome(
        {"field": "evidence.person_name.outcome", "op": op, "value": value}, snap(evidence={"person_name": "pass"})
    )
    assert got == ("pass" if expected else "fail")


@pytest.mark.parametrize(
    "vtype,field",
    [
        (ValueType.TEXT, "extracted.full_name"),
        (ValueType.DATE, "extracted.date_of_birth"),
        (ValueType.NUMBER, "application.document_count"),
        (ValueType.OUTCOME, "evidence.person_name.outcome"),
    ],
)
def test_exists_operators_never_unknown(vtype, field):
    empty = snap()
    empty["documents"][0]["fields"] = {}
    present = snap({"full_name": "X", "date_of_birth": "1990-03-03"}, evidence={"person_name": "pass"})
    assert outcome({"field": field, "op": "exists"}, present) == "pass"
    if vtype in (ValueType.TEXT, ValueType.DATE, ValueType.OUTCOME):
        assert outcome({"field": field, "op": "exists"}, empty) == "fail"
        assert outcome({"field": field, "op": "not_exists"}, empty) == "pass"


def test_every_allowlisted_operator_is_tested():
    tested = {op for op, *_ in TEXT} | {op for op, *_ in DATES} | {op for op, *_ in NUMBERS} | {"exists", "not_exists"}
    assert tested == {op for ops in OPERATORS.values() for op in ops}


# ------------------------------------------------------------------ date boundaries


@pytest.mark.parametrize("dob,expected", [("2008-10-23", "pass"), ("2008-10-24", "fail"), ("2008-10-22", "pass")])
def test_age_on_birthday_boundary(dob, expected):
    assert (
        outcome(
            {"field": "extracted.date_of_birth", "op": "age_years_at_least", "value": 18}, snap({"date_of_birth": dob})
        )
        == expected
    )


@pytest.mark.parametrize("expiry,expected", [("2026-10-24", "pass"), ("2026-10-23", "fail"), ("2026-10-22", "fail")])
def test_document_not_expired_boundary(expiry, expected):
    assert (
        outcome(
            {"field": "extracted.expiry_date", "op": "after_evaluation_date", "value": 0}, snap({"expiry_date": expiry})
        )
        == expected
    )


def test_evaluation_date_offset():
    # must remain valid for at least 30 days after evaluation
    c = {"field": "extracted.expiry_date", "op": "after_evaluation_date", "value": 30}
    assert outcome(c, snap({"expiry_date": "2026-11-23"})) == "pass"
    assert outcome(c, snap({"expiry_date": "2026-11-22"})) == "fail"


# ------------------------------------------------------------------ logic, quantifiers and policies


def test_three_valued_logic():
    missing = {"field": "extracted.national_id", "op": "eq", "value": "X"}
    true = {"field": "extracted.full_name", "op": "exists"}
    false = {"field": "extracted.full_name", "op": "eq", "value": "nobody"}
    s = snap({"full_name": "Test Person"})
    assert outcome({"all": [false, missing]}, s) == "fail"  # FALSE dominates UNKNOWN in all
    assert outcome({"all": [true, missing]}, s) == "insufficient"
    assert outcome({"any": [true, missing]}, s) == "pass"  # TRUE dominates UNKNOWN in any
    assert outcome({"any": [false, missing]}, s) == "insufficient"
    assert outcome({"not": missing}, s) == "insufficient"
    assert outcome({"not": false}, s) == "pass"


def test_quantifiers_across_documents():
    second = {
        "document_id": "d2",
        "name": "synthetic-2.pdf",
        "fields": {
            "full_name": {
                "value": "Other Person",
                "status": "found",
                "quality": "high",
                "value_source": "extracted",
                "field_type": "name",
            }
        },
    }
    s = snap({"full_name": "Test Person"}, extra_docs=[second])
    assert outcome({"field": "extracted.full_name", "op": "eq", "value": "Test Person"}, s) == "fail"
    assert (
        outcome({"field": "extracted.full_name", "op": "eq", "value": "Test Person", "quantifier": "any"}, s) == "pass"
    )


@pytest.mark.parametrize(
    "policy,expected", [("insufficient", "insufficient"), ("review", "review"), ("fail", "fail"), ("pass", "pass")]
)
def test_missing_data_policy(policy, expected):
    s = snap()
    assert (
        outcome({"field": "extracted.national_id", "op": "eq", "value": "X"}, s, missing_data_policy=policy) == expected
    )


def test_missing_policy_fail_respects_advisory_rules():
    assert (
        outcome(
            {"field": "extracted.national_id", "op": "eq", "value": "X"},
            snap(),
            missing_data_policy="fail",
            on_violation="review",
        )
        == "review"
    )


def test_invalid_values_count_as_missing():
    s = snap({"date_of_birth": {"value": None, "status": "invalid"}})
    assert outcome({"field": "extracted.date_of_birth", "op": "before", "value": "2000-01-01"}, s) == "insufficient"


@pytest.mark.parametrize(
    "policy,expected", [("review", "review"), ("insufficient", "insufficient"), ("evaluate", "fail")]
)
def test_low_confidence_policy(policy, expected):
    s = snap({"full_name": {"value": "Tost Porsan", "quality": "low"}})
    r = evaluate(
        rule({"field": "extracted.full_name", "op": "eq", "value": "Test Person"}, low_confidence_policy=policy), s
    )
    assert r["outcome"] == expected
    if policy != "evaluate":
        assert r["would_have_been"] == "fail"


def test_low_confidence_never_confirms_failure_by_default():
    s = snap({"full_name": {"value": "Tost Porsan", "quality": "low"}})
    assert outcome({"field": "extracted.full_name", "op": "eq", "value": "Test Person"}, s) == "review"


def test_stale_evidence_is_low_confidence():
    s = snap(evidence={"person_name": "fail"}, stale=True)
    assert outcome({"field": "evidence.person_name.outcome", "op": "ne", "value": "fail"}, s) == "review"


def test_applicability_and_advisory_violations():
    c = {"field": "extracted.full_name", "op": "eq", "value": "nobody"}
    loan_only = {"field": "application.application_type", "op": "eq", "value": "loan"}
    assert outcome(c, snap({"full_name": "X"}), applies_when=loan_only) == "not_applicable"
    assert outcome(c, snap({"full_name": "X"}, app_type="loan"), applies_when=loan_only) == "fail"
    assert (
        outcome(c, snap({"full_name": "X"}, app_type="loan"), applies_when=loan_only, on_violation="review") == "review"
    )


def test_trace_records_provenance_for_every_leaf():
    r = evaluate(
        rule(
            {
                "all": [
                    {"field": "extracted.date_of_birth", "op": "age_years_at_least", "value": 18},
                    {"field": "evidence.date_of_birth.outcome", "op": "eq", "value": "pass"},
                ]
            }
        ),
        snap({"date_of_birth": "1990-03-03"}, evidence={"date_of_birth": "pass"}),
    )
    leaf1, leaf2 = r["trace"]
    assert leaf1["path"] == "condition.all[0]" and leaf1["result"] is True
    obs = leaf1["observations"][0]
    assert (obs["document_id"], obs["field_id"], obs["page_number"], obs["bbox"], obs["value"]) == (
        "d1",
        "f-date_of_birth",
        1,
        [1, 2, 3, 4],
        "1990-03-03",
    )
    assert leaf2["observations"][0]["finding_id"] == "fi-date_of_birth"


def test_repeatable_outcomes():
    d = rule(
        {
            "any": [
                {"field": "extracted.full_name", "op": "starts_with", "value": "Test"},
                {"field": "extracted.national_id", "op": "exists"},
            ]
        }
    )
    s = snap({"full_name": "Test Person"})
    assert all(evaluate(d, s) == evaluate(d, s) for _ in range(5))


# ------------------------------------------------------------------ invalid rules


@pytest.mark.parametrize(
    "condition,message",
    [
        ({"field": "extracted.full_name", "op": "gt", "value": "a"}, "not allowed for text"),
        ({"field": "extracted.date_of_birth", "op": "contains", "value": "19"}, "not allowed for date"),
        ({"field": "extracted.salary", "op": "eq", "value": "1"}, "unknown field"),
        ({"field": "extracted.date_of_birth", "op": "before", "value": "03/03/1990"}, "valid YYYY-MM-DD"),
        (
            {"field": "extracted.date_of_birth", "op": "between", "value": ["2000-01-01", "1990-01-01"]},
            "range start is after",
        ),
        ({"field": "extracted.full_name", "op": "in", "value": "single"}, "list of"),
        ({"field": "extracted.full_name", "op": "exists", "value": "x"}, "takes no value"),
        ({"field": "extracted.date_of_birth", "op": "age_years_at_least", "value": "18"}, "whole number"),
        ({"field": "application.document_count", "op": "gt", "value": "2"}, "not a number"),
        ({"field": "evidence.person_name.outcome", "op": "eq", "value": "great"}, "is not one of"),
        ({"field": "application.application_type", "op": "eq", "value": "x", "quantifier": "any"}, "quantifier"),
        ({"field": "extracted.full_name", "op": "eval", "value": "__import__('os').system('x')"}, "Input should be"),
        ({"field": "extracted.full_name", "op": "eq", "value": "x", "python": "1"}, "Extra inputs"),
        ({"all": []}, "at least 1"),
        ({"or": [{"field": "extracted.full_name", "op": "exists"}]}, "Field required"),
    ],
)
def test_invalid_rules_rejected(condition, message):
    with pytest.raises(ValidationError, match=message):
        rule(condition)


def test_nesting_and_size_limits():
    deep: dict = {"field": "extracted.full_name", "op": "exists"}
    for _ in range(7):
        deep = {"not": deep}
    with pytest.raises(ValidationError, match="nesting deeper"):
        rule(deep)
    with pytest.raises(ValidationError, match="too many conditions"):
        rule({"any": [{"any": [{"field": "extracted.full_name", "op": "exists"}] * 20}] * 3})


def test_policy_values_are_allowlisted():
    with pytest.raises(ValidationError):
        rule({"field": "extracted.full_name", "op": "exists"}, missing_data_policy="ignore")
    with pytest.raises(ValidationError):
        parse_definition({"condition": {"field": "extracted.full_name", "op": "exists"}, "severity": "extreme"})


def test_readable_summary():
    d = rule(
        {
            "all": [
                {"field": "extracted.date_of_birth", "op": "age_years_at_least", "value": 18},
                {"not": {"field": "evidence.person_name.outcome", "op": "eq", "value": "fail"}},
            ]
        },
        applies_when={"field": "application.application_type", "op": "in", "value": ["loan", "kyc"]},
    )
    s = definition_summary(d)
    assert (
        "Date of birth (every document with a value) is at least 18 years before the evaluation date" in s["condition"]
    )
    assert "NOT:" in s["condition"] and "Evidence: Person name is “fail”" in s["condition"]
    assert s["applies_when"] == "Application type is one of “loan”, “kyc”"
    assert "missing data → insufficient" in s["policies"]
