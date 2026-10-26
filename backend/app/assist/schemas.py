"""Strict output contracts for each AI task.

Two layers: a JSON Schema sent to the provider as a structured-output constraint, and a Pydantic model that
re-validates whatever comes back (``extra="forbid"``, length limits, closed enums). Provider-side constraints
are a convenience; the Pydantic check is what the application relies on.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

DOCUMENT_TYPES: dict[str, str] = {
    "passport": "Passport",
    "national_id_card": "National identity card",
    "driving_licence": "Driving licence",
    "residence_permit": "Residence permit",
    "birth_certificate": "Birth certificate",
    "bank_statement": "Bank statement",
    "utility_bill": "Utility bill",
    "payslip": "Payslip",
    "tax_document": "Tax document",
    "company_registration": "Company registration document",
    "other": "Another kind of document",
    "unknown": "Cannot be determined from the text",
}

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=800)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
RefId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=80)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------ classification


class ClassificationOutput(_Strict):
    document_type: Literal[tuple(DOCUMENT_TYPES)]  # type: ignore[valid-type]
    confidence: Literal["low", "medium", "high"]
    rationale: Annotated[str, StringConstraints(strip_whitespace=True, max_length=600)]
    evidence_pages: list[int] = Field(default_factory=list, max_length=10)


CLASSIFICATION_SCHEMA = {
    "type": "object",
    "properties": {
        "document_type": {"type": "string", "enum": list(DOCUMENT_TYPES)},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "rationale": {"type": "string"},
        "evidence_pages": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["document_type", "confidence", "rationale", "evidence_pages"],
    "additionalProperties": False,
}


# ------------------------------------------------------------------ field suggestions


class FieldSuggestionOutput(_Strict):
    field_key: Annotated[str, StringConstraints(max_length=60)]
    value: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    page_number: int = Field(ge=1, le=10_000)
    quoted_text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class FieldSuggestionsOutput(_Strict):
    suggestions: list[FieldSuggestionOutput] = Field(max_length=40)


def field_suggestions_schema(field_keys: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "suggestions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field_key": {"type": "string", "enum": field_keys},
                        "value": {"type": "string"},
                        "page_number": {"type": "integer"},
                        "quoted_text": {"type": "string"},
                    },
                    "required": ["field_key", "value", "page_number", "quoted_text"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["suggestions"],
        "additionalProperties": False,
    }


# ------------------------------------------------------------------ explanations


class StatementOutput(_Strict):
    text: Text
    references: list[RefId] = Field(min_length=1, max_length=10)


class ExplanationOutput(_Strict):
    statements: list[StatementOutput] = Field(min_length=1, max_length=12)
    limitations: list[ShortText] = Field(default_factory=list, max_length=6)


EXPLANATION_SCHEMA = {
    "type": "object",
    "properties": {
        "statements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "references": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["text", "references"],
                "additionalProperties": False,
            },
        },
        "limitations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["statements", "limitations"],
    "additionalProperties": False,
}
