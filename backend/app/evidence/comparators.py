"""Deterministic pairwise comparators.

Each comparator returns one of:
  pass    values are equal exactly, or after normalizations the group explicitly enables (listed in details)
  fail    values clearly differ (a *candidate* contradiction; the engine may still downgrade it, see engine.py)
  review  values are close but not provably equal (near-miss, token reorder, day/month swap, OCR look-alikes,
          ambiguous input). A human must decide; nothing is silently accepted.

Comparators never invent aliases (nicknames, abbreviations, transliterations). Only equivalences configured
for the group are applied, and every applied normalization is recorded in ``details["normalizations"]``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date

from app.evidence.config import AddressOptions, CodeOptions, DateOptions, NameOptions, TextOptions

# Versions the comparators AND the engine rules (outcome mapping, gap handling). Part of every analysis
# fingerprint: changing behaviour must bump it so stored analyses are reported stale, not silently "current".
VERSION = "evidence-comparators/1.1"

# Character pairs OCR commonly confuses. Used only to *route to review*, never to make values equal.
_OCR_LOOKALIKES = {
    frozenset(p)
    for p in [("O", "0"), ("I", "1"), ("L", "1"), ("I", "L"), ("S", "5"), ("B", "8"), ("Z", "2"), ("G", "6")]
}


@dataclass(frozen=True)
class Comparison:
    result: str  # pass | fail | review
    method: str
    reason: str
    details: dict = field(default_factory=dict)


def _strip_diacritics(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _near_miss_threshold(length: int) -> int:
    """Edits tolerated before a difference is treated as a different value (still never a pass)."""
    return 1 if length <= 8 else 2


# ------------------------------------------------------------------ names


def _name_form(value: str, o: NameOptions) -> tuple[str, list[str]]:
    applied = []
    v = unicodedata.normalize("NFC", value)
    if o.ignore_diacritics and _strip_diacritics(v) != v:
        v, applied = _strip_diacritics(v), [*applied, "diacritics"]
    if o.ignore_punctuation and re.search(r"[.,'’\-]", v):
        v, applied = re.sub(r"[.,'’]", "", v).replace("-", " "), [*applied, "punctuation"]
    collapsed = re.sub(r"\s+", " ", v).strip()
    if collapsed != v:
        applied.append("whitespace")
    v = collapsed
    if o.ignore_case and v.casefold() != v:
        v, applied = v.casefold(), [*applied, "case"]
    return v, applied


def compare_name(a: str, b: str, o: NameOptions) -> Comparison:
    if a == b:
        return Comparison("pass", "exact", "equal")
    fa, na = _name_form(a, o)
    fb, nb = _name_form(b, o)
    applied = sorted(set(na) | set(nb))
    details = {"compared": [fa, fb], "normalizations": applied}
    if fa == fb:
        return Comparison("pass", "approved_normalization", "equal_after_normalization", details)
    ta, tb = fa.split(" "), fb.split(" ")
    if sorted(ta) == sorted(tb):
        if o.allow_token_reorder:
            return Comparison(
                "pass",
                "approved_normalization",
                "equal_after_token_reorder",
                {**details, "normalizations": [*applied, "token_order"]},
            )
        return Comparison("review", "token_comparison", "token_order_differs", details)
    distance = levenshtein(fa, fb)
    if distance <= _near_miss_threshold(max(len(fa), len(fb))):
        return Comparison("review", "edit_distance", "near_match", {**details, "edit_distance": distance})
    shared = set(ta) & set(tb)
    if shared:
        initials = [x for x in ta + tb if len(x.rstrip(".")) == 1]
        reason = "possible_initials" if initials else "partial_token_match"
        return Comparison(
            "review",
            "token_comparison",
            reason,
            {**details, "shared_tokens": sorted(shared), "differing_tokens": sorted(set(ta) ^ set(tb))},
        )
    return Comparison("fail", "token_comparison", "different_values", {**details, "edit_distance": distance})


# ------------------------------------------------------------------ dates


def compare_date(a: str, b: str, o: DateOptions) -> Comparison:
    """Inputs are ISO dates (normalized extraction output or validated corrections)."""
    da, db = date.fromisoformat(a), date.fromisoformat(b)
    if da == db:
        return Comparison("pass", "exact", "equal")
    diff = abs((da - db).days)
    details = {"difference_days": diff, "tolerance_days": o.tolerance_days}
    if diff <= o.tolerance_days:
        return Comparison("pass", "configured_tolerance", "within_tolerance", details)
    if da.day <= 12 and da.month <= 12:
        try:
            swapped = da.replace(day=da.month, month=da.day)
        except ValueError:
            swapped = None
        if swapped == db:
            return Comparison("review", "day_month_swap_check", "possible_day_month_swap", details)
    return Comparison("fail", "exact", "different_values", details)


# ------------------------------------------------------------------ identifiers / document numbers


def _code_form(value: str, o: CodeOptions) -> tuple[str, list[str]]:
    v = value.strip().upper()
    if o.ignore_separators:
        stripped = re.sub(r"[\s\-./]", "", v)
        if stripped != v:
            return stripped, ["separators"]
    return v, []


def _ocr_lookalike_only(a: str, b: str) -> list[int] | None:
    """Positions where a and b differ, if every difference is an OCR look-alike pair; else None."""
    if len(a) != len(b):
        return None
    positions = [i for i, (x, y) in enumerate(zip(a, b, strict=True)) if x != y]
    if positions and all(frozenset((a[i], b[i])) in _OCR_LOOKALIKES for i in positions):
        return positions
    return None


def compare_code(a: str, b: str, o: CodeOptions) -> Comparison:
    if a == b:
        return Comparison("pass", "exact", "equal")
    fa, na = _code_form(a, o)
    fb, nb = _code_form(b, o)
    details = {"compared": [fa, fb], "normalizations": sorted(set(na) | set(nb))}
    if fa == fb:
        return Comparison("pass", "approved_normalization", "equal_after_normalization", details)
    lookalike = _ocr_lookalike_only(fa, fb)
    if lookalike is not None:
        return Comparison(
            "review", "ocr_lookalike_check", "possible_ocr_confusion", {**details, "differing_positions": lookalike}
        )
    if not o.ignore_separators and re.sub(r"[\s\-./]", "", fa) == re.sub(r"[\s\-./]", "", fb):
        # Separators differ but separator-insensitivity is not configured: surface it, don't decide.
        return Comparison("review", "exact", "separators_differ", details)
    return Comparison("fail", "exact", "different_values", {**details, "edit_distance": levenshtein(fa, fb)})


# ------------------------------------------------------------------ addresses


def _address_tokens(value: str, o: AddressOptions) -> tuple[list[str], list[str]]:
    applied: list[str] = []
    v = unicodedata.normalize("NFC", value)
    if o.ignore_case and v.casefold() != v:
        v, applied = v.casefold(), ["case"]
    if o.ignore_punctuation and re.search(r"[.,;#]", v):
        v, applied = re.sub(r"[.,;#]", " ", v), [*applied, "punctuation"]
    tokens = v.split()
    if o.abbreviations:
        mapped = [o.abbreviations.get(t, t) for t in tokens]
        if mapped != tokens:
            tokens, applied = mapped, [*applied, "configured_abbreviations"]
    return tokens, applied


def compare_address(a: str, b: str, o: AddressOptions) -> Comparison:
    if a == b:
        return Comparison("pass", "exact", "equal")
    ta, na = _address_tokens(a, o)
    tb, nb = _address_tokens(b, o)
    details = {"compared": [" ".join(ta), " ".join(tb)], "normalizations": sorted(set(na) | set(nb) | {"line_breaks"})}
    if ta == tb:
        return Comparison("pass", "approved_normalization", "equal_after_normalization", details)
    sa, sb = set(ta), set(tb)
    overlap = len(sa & sb) / len(sa | sb)
    details["token_overlap"] = round(overlap, 3)
    details["differing_tokens"] = sorted(sa ^ sb)
    if overlap >= 0.6:
        return Comparison("review", "token_overlap", "partial_address_match", details)
    return Comparison("fail", "token_overlap", "different_values", details)


# ------------------------------------------------------------------ configurable plain text


def compare_text(a: str, b: str, o: TextOptions) -> Comparison:
    if a == b:
        return Comparison("pass", "exact", "equal")
    fa, fb, applied = a, b, []
    if o.ignore_whitespace:
        fa, fb, applied = re.sub(r"\s+", " ", fa).strip(), re.sub(r"\s+", " ", fb).strip(), ["whitespace"]
    if o.ignore_case:
        fa, fb, applied = fa.casefold(), fb.casefold(), [*applied, "case"]
    details = {"compared": [fa, fb], "normalizations": applied}
    if fa == fb:
        return Comparison("pass", "approved_normalization", "equal_after_normalization", details)
    return Comparison("fail", "exact", "different_values", details)


def compare(comparator: str, a: str, b: str, options) -> Comparison:  # noqa: ANN001
    return {
        "name": compare_name,
        "date": compare_date,
        "identifier": compare_code,
        "document_number": compare_code,
        "address": compare_address,
        "text": compare_text,
    }[comparator](a, b, options)
