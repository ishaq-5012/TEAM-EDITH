"""Comparator, priority and config unit tests: false mismatches, OCR noise, aliases, tolerances."""

from __future__ import annotations

import json

import pytest

from app.evidence.comparators import compare_address, compare_code, compare_date, compare_name, compare_text
from app.evidence.config import (
    AddressOptions,
    CodeOptions,
    ComparisonConfigError,
    DateOptions,
    NameOptions,
    TextOptions,
    load_config,
    parse_config,
)

STRICT_NAME = NameOptions()
LENIENT_NAME = NameOptions(ignore_case=True, ignore_diacritics=True, ignore_punctuation=True)


# ------------------------------------------------------------------ names


@pytest.mark.parametrize(
    "a,b",
    [
        ("Test Person Alpha", "TEST PERSON ALPHA"),
        ("José Núñez", "Jose Nunez"),
        ("Anne-Marie O'Neil", "Anne Marie ONeil"),
        ("Test  Person   Alpha", "Test Person Alpha"),
    ],
)
def test_names_equal_after_configured_normalization(a, b):
    r = compare_name(a, b, LENIENT_NAME)
    assert (r.result, r.method) == ("pass", "approved_normalization")
    assert r.details["normalizations"]  # every applied normalization is listed


def test_normalizations_are_not_applied_unless_configured():
    assert compare_name("Test Person", "TEST PERSON", STRICT_NAME).result != "pass"
    assert compare_name("José", "Jose", NameOptions(ignore_case=True)).result != "pass"


def test_identical_names_pass_exactly():
    assert compare_name("Test Person", "Test Person", STRICT_NAME).method == "exact"


@pytest.mark.parametrize(
    "a,b,reason",
    [
        ("Test Person Alpha", "Test Persn Alpha", "near_match"),  # typo / OCR drop: never auto-accepted
        ("Alpha Test Person", "Test Person Alpha", "token_order_differs"),
        ("Robert Test", "Bob Test", "partial_token_match"),  # no nickname aliases are invented
        ("T. Person", "Test Person", "possible_initials"),
    ],
)
def test_close_names_require_review(a, b, reason):
    r = compare_name(a, b, LENIENT_NAME)
    assert (r.result, r.reason) == ("review", reason)


def test_token_reorder_passes_only_when_configured():
    r = compare_name("Alpha Test Person", "Test Person Alpha", NameOptions(ignore_case=True, allow_token_reorder=True))
    assert r.result == "pass" and "token_order" in r.details["normalizations"]


def test_clearly_different_names_fail():
    r = compare_name("Test Person Alpha", "Other Applicant Zeta", LENIENT_NAME)
    assert (r.result, r.reason) == ("fail", "different_values")


# ------------------------------------------------------------------ dates


def test_dates():
    assert compare_date("1990-03-03", "1990-03-03", DateOptions()).result == "pass"
    assert compare_date("1990-03-03", "1990-03-04", DateOptions()).result == "fail"
    tol = compare_date("2024-01-15", "2024-01-17", DateOptions(tolerance_days=2))
    assert (tol.result, tol.method, tol.details["difference_days"]) == ("pass", "configured_tolerance", 2)
    assert compare_date("2024-01-15", "2024-01-18", DateOptions(tolerance_days=2)).result == "fail"
    swap = compare_date("1990-03-04", "1990-04-03", DateOptions())
    assert (swap.result, swap.reason) == ("review", "possible_day_month_swap")


# ------------------------------------------------------------------ identifiers / document numbers


def test_identifier_separators_only_when_configured():
    on = compare_code("TEST-0001-AB", "TEST 0001 AB", CodeOptions(ignore_separators=True))
    assert (on.result, on.details["normalizations"]) == ("pass", ["separators"])
    off = compare_code("TEST-0001-AB", "TEST 0001 AB", CodeOptions(ignore_separators=False))
    assert (off.result, off.reason) == ("review", "separators_differ")


def test_ocr_lookalikes_route_to_review_never_pass():
    r = compare_code("TEST-0001-AB", "TEST-OOO1-AB", CodeOptions())
    assert (r.result, r.reason) == ("review", "possible_ocr_confusion")
    assert r.details["differing_positions"] == [5, 6, 7]


def test_different_identifiers_fail():
    r = compare_code("TEST-0001-AB", "TEST-0042-XY", CodeOptions(ignore_separators=True))
    assert r.result == "fail"


# ------------------------------------------------------------------ addresses and text


def test_addresses():
    o = AddressOptions(ignore_case=True, ignore_punctuation=True)
    assert (
        compare_address("1 Synthetic Street\nTestville\nTS1 0AA", "1 synthetic street, testville, TS1 0AA", o).result
        == "pass"
    )
    # "St" vs "Street" is an alias: not equal unless configured.
    unconfigured = compare_address("1 Synthetic St\nTestville", "1 Synthetic Street\nTestville", o)
    assert unconfigured.result == "review"
    configured = compare_address(
        "1 Synthetic St\nTestville",
        "1 Synthetic Street\nTestville",
        AddressOptions(ignore_case=True, abbreviations={"st": "street"}),
    )
    assert configured.result == "pass" and "configured_abbreviations" in configured.details["normalizations"]
    assert compare_address("1 Synthetic Street\nTestville", "99 Other Road\nElsewhere", o).result == "fail"


def test_text_comparator():
    assert compare_text("a  b", "A B", TextOptions(ignore_case=True, ignore_whitespace=True)).result == "pass"
    assert compare_text("a b", "A B", TextOptions()).result == "fail"


# ------------------------------------------------------------------ config


def test_default_config_loads_with_stable_hash():
    cfg, h = load_config()
    again, h2 = parse_config(json.dumps(cfg.model_dump(mode="json")))
    assert h == h2 and {g.comparator for g in cfg.groups} >= {
        "name",
        "date",
        "identifier",
        "address",
        "document_number",
    }


@pytest.mark.parametrize(
    "mutate,msg",
    [
        (lambda c: c["groups"][0]["options"].update(nickname_aliases=True), "Extra inputs"),
        (lambda c: c["groups"][1]["options"].update(tolerance_days=-1), "greater than or equal"),
        (lambda c: c["groups"].append(dict(c["groups"][0])), "duplicate group keys"),
        (lambda c: c["groups"][1]["fields"].append("full_name"), "more than one group"),
        (lambda c: c["groups"][0].update(severity="urgent"), "Input should be"),
        (lambda c: c["groups"][0].update(min_values=1), "greater than or equal"),
    ],
)
def test_invalid_config_rejected(mutate, msg):
    cfg, _ = load_config()
    raw = cfg.model_dump(mode="json")
    mutate(raw)
    with pytest.raises(ComparisonConfigError, match=msg):
        parse_config(json.dumps(raw))
