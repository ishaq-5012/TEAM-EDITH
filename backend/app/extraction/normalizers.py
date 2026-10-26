"""Field-specific normalization into strict Pydantic value schemas.

There is deliberately no universal normalizer. Each field type has its own rules, and none of
them alters the raw value, which is stored separately exactly as found. Normalization never
"repairs" content: OCR look-alikes (O/0, I/l/1) are flagged for a human, never substituted.
"""

from __future__ import annotations

import calendar
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.extraction.definitions import FieldDefinition, FieldType

# ------------------------------------------------------------------ strict value schemas


class _Strict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class NameValue(_Strict):
    full: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class TextValue(_Strict):
    value: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class DateValue(_Strict):
    iso: date


class IdentifierValue(_Strict):
    value: Annotated[str, StringConstraints(min_length=1, max_length=80)]


class AddressValue(_Strict):
    lines: list[Annotated[str, StringConstraints(min_length=1, max_length=200)]] = Field(min_length=1, max_length=6)


class DocumentNumberValue(_Strict):
    value: Annotated[str, StringConstraints(min_length=1, max_length=80)]


Status = Literal["found", "invalid", "ambiguous"]


@dataclass
class Normalized:
    status: Status
    value: str | None  # canonical string form (None when invalid)
    data: dict[str, Any] | None  # strict schema dump
    note: str | None = None
    flags: list[str] = field(default_factory=list)


def _clean(text: str) -> str:
    """Unicode NFC + collapse runs of whitespace. Used inside field normalizers only."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


# A look-alike letter directly touching a digit (or vice versa), e.g. "3l", "O1", "A0B". These are
# the positions where OCR confuses O/0 and I/l/1. Separated groups such as "ACCT-0001" are not flagged.
_OCR_LOOKALIKE = re.compile(r"[OoIl](?=\d)|(?<=\d)[OoIl]|[01](?=[A-Za-z])|(?<=[A-Za-z])[01]")


def _ocr_confusion(value: str, from_ocr: bool) -> list[str]:
    return ["possible_ocr_confusion"] if from_ocr and _OCR_LOOKALIKE.search(value) else []


# ------------------------------------------------------------------ names


def normalize_text(raw: str, definition: FieldDefinition, from_ocr: bool = False) -> Normalized:
    value = _clean(raw).strip(" ,;:.")
    note = None
    if definition.strip_trailing_code:
        stripped = re.sub(r"\s+\([A-Z]{2,10}-[A-Z0-9-]{2,40}\)$", "", value)
        if stripped != value:
            value = stripped
            note = "Trailing programme code omitted from the comparison value; the original text is retained."
    if definition.strip_inline_intake:
        stripped = re.sub(r";\s*intake\s*:\s*[0-9]+\.?\s*$", "", value, flags=re.I)
        if stripped != value:
            value = stripped
            note = "Inline intake omitted from the programme comparison value; the original text is retained."
    if not value or len(value) > 200:
        return Normalized("invalid", None, None, "Text is empty or longer than 200 characters")
    v = TextValue(value=value)
    return Normalized("found", v.value, v.model_dump(mode="json"), note, _ocr_confusion(value, from_ocr))


def normalize_name(raw: str, _: FieldDefinition, from_ocr: bool = False) -> Normalized:
    value = _clean(raw).strip(" ,;:.")
    if not value or not any(c.isalpha() for c in value):
        return Normalized("invalid", None, None, "A name must contain letters")
    digits = sum(c.isdigit() for c in value)
    if digits / len(value) > 0.15:
        return Normalized("invalid", None, None, "Too many digits for a name", _ocr_confusion(value, from_ocr))
    if len(value) > 200:
        return Normalized("invalid", None, None, "Name is longer than 200 characters")
    v = NameValue(full=value)
    return Normalized("found", v.full, v.model_dump(mode="json"))


# ------------------------------------------------------------------ dates

_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
_MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})
_MONTHS["sept"] = 9
_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))
_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_NUMERIC = re.compile(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})$")
_DAY_MONTH_YEAR = re.compile(rf"^(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_RE})\.?,?\s+(\d{{4}})$", re.I)
_MONTH_DAY_YEAR = re.compile(rf"^({_MONTH_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})$", re.I)
MIN_YEAR, MAX_YEAR = 1900, 2100


def _build_date(y: int, m: int, d: int) -> tuple[date | None, str | None]:
    if not MIN_YEAR <= y <= MAX_YEAR:
        return None, f"Year {y} is outside the accepted range {MIN_YEAR}–{MAX_YEAR}"
    if not 1 <= m <= 12:
        return None, f"Month {m} does not exist"
    last = calendar.monthrange(y, m)[1]
    if not 1 <= d <= last:
        return None, f"{calendar.month_name[m]} {y} has no day {d}"
    return date(y, m, d), None


def normalize_date(raw: str, definition: FieldDefinition, from_ocr: bool = False) -> Normalized:
    text = _clean(raw).rstrip(".")
    flags = _ocr_confusion(text, from_ocr)
    order = definition.date_order or "DMY"
    ambiguous = False
    if m := _ISO.match(text):
        y, mo, d = int(m[1]), int(m[2]), int(m[3])
    elif m := _NUMERIC.match(text):
        a, b, year = int(m[1]), int(m[2]), m[3]
        if len(year) != 4:
            return Normalized("invalid", None, None, "Two-digit years are not accepted (century is ambiguous)", flags)
        y = int(year)
        d, mo = (a, b) if order == "DMY" else (b, a)
        ambiguous = a <= 12 and b <= 12 and a != b
    elif m := _DAY_MONTH_YEAR.match(text):
        d, mo, y = int(m[1]), _MONTHS[m[2].lower()], int(m[3])
    elif m := _MONTH_DAY_YEAR.match(text):
        mo, d, y = _MONTHS[m[1].lower()], int(m[2]), int(m[3])
    else:
        return Normalized("invalid", None, None, f"Not a recognised date format: “{text}”", flags)

    value, problem = _build_date(y, mo, d)
    if value is None:
        return Normalized("invalid", None, None, problem, flags)
    v = DateValue(iso=value)
    if ambiguous:
        note = f"Day and month are ambiguous; interpreted as {order} ({value.isoformat()}). Confirm against the source."
        return Normalized(
            "ambiguous", value.isoformat(), v.model_dump(mode="json"), note, [*flags, "ambiguous_day_month"]
        )
    return Normalized("found", value.isoformat(), v.model_dump(mode="json"), None, flags)


# ------------------------------------------------------------------ identifiers / document numbers


def _code(raw: str, definition: FieldDefinition, from_ocr: bool, *, allow_spaces: bool) -> tuple[str, list[str]]:
    value = _clean(raw)
    if definition.uppercase:
        value = value.upper()
    if not allow_spaces:
        value = value.replace(" ", "")
    if definition.remove_separators:
        value = re.sub(r"[\s\-/.]", "", value)
    return value, _ocr_confusion(value, from_ocr)


def normalize_identifier(raw: str, definition: FieldDefinition, from_ocr: bool = False) -> Normalized:
    value, flags = _code(raw, definition, from_ocr, allow_spaces=False)
    if definition.pattern and not re.fullmatch(definition.pattern, value):
        return Normalized("invalid", None, None, f"“{value}” does not match the expected format", flags)
    v = IdentifierValue(value=value)
    return Normalized("found", v.value, v.model_dump(mode="json"), None, flags)


def normalize_document_number(raw: str, definition: FieldDefinition, from_ocr: bool = False) -> Normalized:
    value, flags = _code(raw, definition, from_ocr, allow_spaces=True)
    if definition.pattern and not re.fullmatch(definition.pattern, value):
        return Normalized("invalid", None, None, f"“{value}” does not match the expected format", flags)
    v = DocumentNumberValue(value=value)
    return Normalized("found", v.value, v.model_dump(mode="json"), None, flags)


# ------------------------------------------------------------------ addresses


def normalize_address(raw: str, definition: FieldDefinition, from_ocr: bool = False) -> Normalized:
    lines = [_clean(line).strip(" ,;") for line in raw.splitlines()]
    lines = [line for line in lines if line]
    if not lines or not any(any(c.isalnum() for c in line) for line in lines):
        return Normalized("invalid", None, None, "Address is empty")
    limit = definition.max_lines or 6
    flags: list[str] = []
    if len(lines) > limit:
        flags.append("address_truncated")
        lines = lines[:limit]
    v = AddressValue(lines=lines)
    return Normalized("found", "\n".join(v.lines), v.model_dump(mode="json"), None, flags)


NORMALIZERS = {
    FieldType.TEXT: normalize_text,
    FieldType.NAME: normalize_name,
    FieldType.DATE: normalize_date,
    FieldType.IDENTIFIER: normalize_identifier,
    FieldType.ADDRESS: normalize_address,
    FieldType.DOCUMENT_NUMBER: normalize_document_number,
}


def normalize(raw: str, definition: FieldDefinition, from_ocr: bool = False) -> Normalized:
    return NORMALIZERS[definition.type](raw, definition, from_ocr)
