"""Comparison groups: which extracted fields are compared across documents, and how.

Loaded from ``comparison_config.json`` (override with VERIFYFLOW_COMPARISON_CONFIG_PATH) and validated
strictly. Every tolerance or normalization a comparator may apply must be enabled here explicitly; the
comparators never assume an equivalence that is not configured.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, model_validator

DEFAULT_PATH = Path(__file__).with_name("comparison_config.json")
Key = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,59}$")]


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class _Opts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class NameOptions(_Opts):
    ignore_case: bool = False
    ignore_diacritics: bool = False
    ignore_punctuation: bool = False
    allow_token_reorder: bool = False


class DateOptions(_Opts):
    tolerance_days: int = Field(default=0, ge=0, le=3650)


class CodeOptions(_Opts):
    ignore_separators: bool = False


class AddressOptions(_Opts):
    ignore_case: bool = False
    ignore_punctuation: bool = False
    # Explicit, configured equivalences only, e.g. {"st": "street"}. Keys/values are lower-case single tokens.
    abbreviations: dict[
        Annotated[str, StringConstraints(pattern=r"^[a-z0-9]{1,20}$")],
        Annotated[str, StringConstraints(pattern=r"^[a-z0-9]{1,30}$")],
    ] = Field(default_factory=dict)


class TextOptions(_Opts):
    ignore_case: bool = False
    ignore_whitespace: bool = False


OPTIONS_BY_COMPARATOR: dict[str, type[_Opts]] = {
    "name": NameOptions,
    "date": DateOptions,
    "identifier": CodeOptions,
    "document_number": CodeOptions,
    "address": AddressOptions,
    "text": TextOptions,
}


class ComparisonGroup(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: Key
    scope: Literal["all", "general", "portal"] = "all"
    label: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    comparator: Literal["name", "date", "identifier", "document_number", "address", "text"]
    fields: list[Key] = Field(min_length=1, max_length=10)  # extracted field keys pooled into this group
    severity: Severity
    impacts: list[Key] = Field(default_factory=list, max_length=10)  # downstream decisions depending on this
    min_values: int = Field(default=2, ge=2, le=50)  # values needed before anything can be concluded
    options: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_options(self) -> ComparisonGroup:
        # Re-validate options strictly against the comparator's schema (unknown keys rejected).
        parsed = OPTIONS_BY_COMPARATOR[self.comparator].model_validate(self.options)
        object.__setattr__(self, "options", parsed.model_dump())
        return self

    def opts(self) -> _Opts:
        return OPTIONS_BY_COMPARATOR[self.comparator].model_validate(self.options)


class ComparisonConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Annotated[str, StringConstraints(min_length=1, max_length=40)]
    groups: list[ComparisonGroup] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def _unique(self) -> ComparisonConfig:
        keys = [g.key for g in self.groups]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate group keys")
        fields = [f for g in self.groups for f in g.fields]
        dupes = sorted({f for f in fields if fields.count(f) > 1})
        if dupes:
            raise ValueError(f"field(s) used in more than one group: {', '.join(dupes)}")
        return self


class ComparisonConfigError(RuntimeError):
    pass


def parse_config(raw: str | bytes) -> tuple[ComparisonConfig, str]:
    try:
        cfg = ComparisonConfig.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ComparisonConfigError(f"Invalid comparison config: {exc}") from None
    canonical = json.dumps(cfg.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return cfg, hashlib.sha256(canonical.encode()).hexdigest()


@lru_cache(maxsize=4)
def load_config(path: str | None = None) -> tuple[ComparisonConfig, str]:
    target = Path(path) if path else DEFAULT_PATH
    try:
        return parse_config(target.read_bytes())
    except OSError as exc:
        raise ComparisonConfigError(f"Cannot read comparison config at {target}: {exc}") from None
