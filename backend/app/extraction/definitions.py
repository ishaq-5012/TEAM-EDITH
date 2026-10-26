"""Configurable field definitions.

Definitions live in a JSON file (default: ``field_definitions.json`` next to this module; override with
VERIFYFLOW_FIELD_DEFINITIONS_PATH). They are validated strictly at load: unknown keys, duplicate field
keys, empty labels, options that don't apply to the field type, and invalid regexes are all rejected.
The canonical-JSON SHA-256 of the definitions is recorded on every extraction run, so a run can always
be traced to the exact definitions that produced it.
"""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator, model_validator

DEFAULT_PATH = Path(__file__).with_name("field_definitions.json")
PORTAL_DOCUMENT_TYPES = frozenset({
    "registration", "approval", "land", "building", "safety", "faculty", "programme",
    "infrastructure", "library", "affiliation", "finance", "declaration", "explanation",
})

Key = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,59}$")]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class FieldType(StrEnum):
    TEXT = "text"
    NAME = "name"
    DATE = "date"
    IDENTIFIER = "identifier"
    ADDRESS = "address"
    DOCUMENT_NUMBER = "document_number"


class FieldDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: Key
    label: Label
    type: FieldType
    # Text labels that precede the value in the document, e.g. "Date of birth". Matched case-insensitively and
    # must be followed by ":" or a dash on the same line.
    labels: list[Label] = Field(min_length=1, max_length=20)
    scope: Literal["all", "general", "portal"] = "all"
    document_types: list[str] = Field(default_factory=list)  # empty: applies to every document
    required_for: list[str] = Field(default_factory=list)  # document types where a missing value needs review
    # date
    date_order: Literal["DMY", "MDY"] | None = None
    # identifier / document_number
    pattern: str | None = Field(default=None, max_length=200)
    uppercase: bool | None = None
    remove_separators: bool | None = None
    # address
    max_lines: int | None = Field(default=None, ge=1, le=6)
    # text
    strip_trailing_code: bool | None = None
    strip_inline_intake: bool | None = None

    @field_validator("pattern")
    @classmethod
    def _regex(cls, v: str | None) -> str | None:
        if v is not None:
            try:
                re.compile(v)
            except re.error as exc:
                raise ValueError(f"invalid regular expression: {exc}") from None
        return v

    @model_validator(mode="after")
    def _options_match_type(self) -> FieldDefinition:
        def only(option: str, *types: FieldType) -> None:
            if getattr(self, option) is not None and self.type not in types:
                raise ValueError(f"'{option}' does not apply to {self.type.value} fields")

        only("date_order", FieldType.DATE)
        only("pattern", FieldType.IDENTIFIER, FieldType.DOCUMENT_NUMBER)
        only("uppercase", FieldType.IDENTIFIER, FieldType.DOCUMENT_NUMBER)
        only("remove_separators", FieldType.IDENTIFIER)
        only("max_lines", FieldType.ADDRESS)
        only("strip_trailing_code", FieldType.TEXT)
        only("strip_inline_intake", FieldType.TEXT)
        if len({label.casefold() for label in self.labels}) != len(self.labels):
            raise ValueError("duplicate labels")
        return self

    def applies_to(self, document_type: str | None) -> bool:
        if self.scope == "portal" and document_type not in PORTAL_DOCUMENT_TYPES:
            return False
        if self.scope == "general" and document_type in PORTAL_DOCUMENT_TYPES:
            return False
        return not self.document_types or (document_type is not None and document_type in self.document_types)


class FieldDefinitionSet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Annotated[str, StringConstraints(min_length=1, max_length=40)]
    fields: list[FieldDefinition] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _unique_keys(self) -> FieldDefinitionSet:
        keys = [f.key for f in self.fields]
        dupes = sorted({k for k in keys if keys.count(k) > 1})
        if dupes:
            raise ValueError(f"duplicate field keys: {', '.join(dupes)}")
        return self


class DefinitionsError(RuntimeError):
    pass


def parse_definitions(raw: str | bytes) -> tuple[FieldDefinitionSet, str]:
    """Validate definitions JSON; return the set and its canonical SHA-256."""
    try:
        data = json.loads(raw)
        defs = FieldDefinitionSet.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise DefinitionsError(f"Invalid field definitions: {exc}") from None
    canonical = json.dumps(defs.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return defs, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@lru_cache(maxsize=4)
def load_definitions(path: str | None = None) -> tuple[FieldDefinitionSet, str]:
    target = Path(path) if path else DEFAULT_PATH
    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise DefinitionsError(f"Cannot read field definitions at {target}: {exc}") from None
    return parse_definitions(raw)
