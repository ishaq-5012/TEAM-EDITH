"""Synthetic test cases for rules, and conversion into the engine's snapshot format.

A case must declare ``"synthetic": true``. It describes invented documents and values only; it is
never built from real application data. Field keys must exist in the field definitions.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.evidence.config import load_config
from app.extraction.definitions import load_definitions

Outcome = Literal["pass", "fail", "review", "insufficient"]
ExpectedOutcome = Literal["pass", "fail", "review", "insufficient", "not_applicable"]
_STRICT = ConfigDict(extra="forbid", frozen=True)


class CaseField(BaseModel):
    model_config = _STRICT
    value: Annotated[str, StringConstraints(max_length=500)] | None = None
    status: Literal["found", "missing", "invalid", "ambiguous"] = "found"
    quality: Literal["high", "medium", "low"] = "high"
    source: Literal["extracted", "correction"] = "extracted"


class CaseDocument(BaseModel):
    model_config = _STRICT
    name: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    fields: dict[str, CaseField] = Field(default_factory=dict)

    @field_validator("fields")
    @classmethod
    def _known_keys(cls, v: dict[str, CaseField]) -> dict[str, CaseField]:
        known = {f.key for f in load_definitions()[0].fields}
        unknown = sorted(set(v) - known)
        if unknown:
            raise ValueError(f"unknown field key(s): {', '.join(unknown)}")
        return v


class CaseEvidence(BaseModel):
    model_config = _STRICT
    outcome: Outcome
    quality: Literal["high", "medium", "low"] = "high"


class CaseApplication(BaseModel):
    model_config = _STRICT
    application_type: Annotated[str, StringConstraints(min_length=1, max_length=60)] = "synthetic"
    document_count: int | None = Field(default=None, ge=0, le=1000)


class SyntheticCase(BaseModel):
    model_config = _STRICT
    synthetic: Literal[True]
    evaluation_date: date
    application: CaseApplication = CaseApplication()
    documents: list[CaseDocument] = Field(default_factory=list, max_length=20)
    evidence: dict[str, CaseEvidence] | None = None  # None = no evidence analysis exists
    evidence_stale: bool = False

    @field_validator("evidence")
    @classmethod
    def _known_groups(cls, v: dict[str, CaseEvidence] | None) -> dict[str, CaseEvidence] | None:
        if v:
            known = {g.key for g in load_config()[0].groups}
            unknown = sorted(set(v) - known)
            if unknown:
                raise ValueError(f"unknown evidence group(s): {', '.join(unknown)}")
        return v

    def to_snapshot(self) -> dict:
        types = {f.key: f.type.value for f in load_definitions()[0].fields}
        docs = []
        for i, d in enumerate(self.documents):
            fields = {}
            for key, f in d.fields.items():
                fields[key] = {
                    "value": f.value if f.status != "missing" else None,
                    "raw_value": f.value,
                    "status": f.status,
                    "quality": f.quality,
                    "value_source": "correction" if f.source == "correction" else "extracted",
                    "field_type": types[key],
                    "field_id": None,
                    "extraction_run_id": None,
                    "correction_id": None,
                    "page_number": None,
                    "bbox": None,
                }
            docs.append({"document_id": f"synthetic-{i + 1}", "name": d.name, "fields": fields})
        evidence = None
        if self.evidence is not None:
            evidence = {
                "analysis_id": "synthetic",
                "stale": self.evidence_stale,
                "outcomes": {
                    k: {"outcome": e.outcome, "finding_id": None, "evidence_quality": e.quality}
                    for k, e in self.evidence.items()
                },
            }
        return {
            "synthetic": True,
            "evaluation_date": self.evaluation_date.isoformat(),
            "application": {
                "application_type": self.application.application_type,
                "document_count": self.application.document_count
                if self.application.document_count is not None
                else len(self.documents),
            },
            "documents": docs,
            "evidence": evidence,
        }
