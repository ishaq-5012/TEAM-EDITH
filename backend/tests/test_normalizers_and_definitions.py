"""Field-specific normalizers and strict field-definition loading."""

from __future__ import annotations

import json

import pytest

from app.extraction.definitions import DefinitionsError, FieldDefinition, FieldType, load_definitions, parse_definitions
from app.extraction.normalizers import (
    normalize_address,
    normalize_date,
    normalize_document_number,
    normalize_identifier,
    normalize_name,
)


def d(**kw) -> FieldDefinition:  # noqa: ANN003
    base = {"key": "test_field", "label": "Test field", "labels": ["Test field"], "type": "name"}
    return FieldDefinition.model_validate(base | kw)


def test_default_definitions_load_and_hash_is_stable():
    a, h1 = load_definitions()
    b, h2 = parse_definitions(json.dumps(a.model_dump(mode="json"), indent=4))
    assert h1 == h2 and len(h1) == 64
    assert {f.type for f in a.fields} == set(FieldType)


@pytest.mark.parametrize(
    "mutate,message",
    [
        (lambda c: c["fields"][0].update(bogus=1), "Extra inputs are not permitted"),
        (lambda c: c["fields"].append(dict(c["fields"][0])), "duplicate field keys"),
        (lambda c: c["fields"][0].update(labels=[]), "at least 1"),
        (lambda c: c["fields"][0].update(date_order="DMY"), "does not apply to name"),
        (lambda c: c["fields"][4].update(pattern="(unclosed"), "invalid regular expression"),
        (lambda c: c["fields"][0].update(type="salary"), "Input should be"),
        (lambda c: c["fields"][0].update(labels=["Name", "name"]), "duplicate labels"),
        (lambda c: c.update(version=""), "at least 1"),
    ],
)
def test_invalid_definitions_are_rejected(mutate, message):
    config, _ = load_definitions()
    raw = config.model_dump(mode="json")
    mutate(raw)
    with pytest.raises(DefinitionsError, match=message):
        parse_definitions(json.dumps(raw))


def test_not_json_is_rejected():
    with pytest.raises(DefinitionsError):
        parse_definitions(b"{not json")


# ------------------------------------------------------------------ names


def test_name_collapses_whitespace_but_keeps_case_and_diacritics():
    r = normalize_name("  José   de la  Cruz-O'Neil, ", d())
    assert r.status == "found" and r.value == "José de la Cruz-O'Neil"


@pytest.mark.parametrize("raw", ["12345", "", "  ,  ", "A1234567"])
def test_name_rejections(raw):
    assert normalize_name(raw, d()).status == "invalid"


# ------------------------------------------------------------------ dates


@pytest.mark.parametrize(
    "raw,iso",
    [
        ("2024-02-29", "2024-02-29"),
        ("29.02.2024", "2024-02-29"),
        ("1st March 2020", "2020-03-01"),
        ("Sept 9, 2001", "2001-09-09"),
        ("09 Sep 2001", "2001-09-09"),
        ("13/01/2000", "2000-01-13"),
    ],
)
def test_date_formats(raw, iso):
    r = normalize_date(raw, d(type="date", date_order="DMY"))
    assert (r.status, r.value) == ("found", iso)


def test_mdy_order_is_respected_and_ambiguity_reported():
    r = normalize_date("03/04/2026", d(type="date", date_order="MDY"))
    assert r.status == "ambiguous" and r.value == "2026-03-04" and "ambiguous_day_month" in r.flags
    assert normalize_date("2023-02-29", d(type="date")).status == "invalid"  # not a leap year


# ------------------------------------------------------------------ identifiers and document numbers


def test_identifier_normalization_is_configurable_and_not_destructive_by_default():
    ident = d(type="identifier", uppercase=True, remove_separators=False, pattern=r"^[A-Z0-9-]+$")
    assert normalize_identifier(" ab-12 3 ", ident).value == "AB-123"
    stripped = d(type="identifier", uppercase=True, remove_separators=True)
    assert normalize_identifier("ab-12/3.4", stripped).value == "AB1234"
    assert normalize_identifier("ab_12", ident).status == "invalid"


def test_ocr_lookalikes_flagged_only_for_ocr_sources():
    ident = d(type="identifier", uppercase=True)
    assert normalize_identifier("ID-0O1", ident, from_ocr=True).flags == ["possible_ocr_confusion"]
    assert normalize_identifier("ID-0O1", ident, from_ocr=False).flags == []
    assert normalize_identifier("ACCT-0001", ident, from_ocr=True).flags == []


def test_document_number_keeps_internal_spaces():
    r = normalize_document_number("  syn   000 123 ", d(type="document_number", uppercase=True))
    assert r.value == "SYN 000 123"


# ------------------------------------------------------------------ addresses


def test_address_lines_and_truncation():
    r = normalize_address("1  Synthetic Street,\n\n Testville ,\nTS1 0AA", d(type="address", max_lines=2))
    assert r.value == "1 Synthetic Street\nTestville" and "address_truncated" in r.flags
    assert normalize_address(" , \n ;", d(type="address")).status == "invalid"
