from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from app.schemas.application import UserRef
from app.schemas.common import ORMModel

TrustState = Literal["verified", "failed", "unsupported", "inconclusive"]


class CheckOut(BaseModel):
    dimension: str
    key: str
    label: str
    state: TrustState
    code: str
    method: str
    summary: str
    establishes: str
    does_not_establish: list[str]
    limitations: list[str]
    evidence: dict[str, Any]
    subject: str | None
    checked_at: str


class VerificationOut(ORMModel):
    id: str
    application_id: str
    document_id: str
    recorded_sha256: str
    observed_sha256: str | None
    engine_version: str
    config: dict[str, Any]
    checks: list[CheckOut]
    signatures: list[dict[str, Any]]
    summary: dict[str, TrustState]
    created_by: UserRef
    created_at: datetime


class VerificationSummary(ORMModel):
    id: str
    recorded_sha256: str
    observed_sha256: str | None
    summary: dict[str, TrustState]
    created_by: UserRef
    created_at: datetime


class DocRef(ORMModel):
    id: str
    application_id: str
    original_filename: str
    detected_mime: str
    size_bytes: int
    sha256: str
    created_at: datetime


class AppRef(ORMModel):
    id: str
    reference: str
    title: str
    status: str


class HistoryOut(BaseModel):
    application: AppRef
    document: DocRef
    verifications: list[VerificationSummary]
    same_hash_documents: list[dict[str, str]]
    can_verify: bool


class OverviewRow(BaseModel):
    document: DocRef
    application: AppRef
    latest: VerificationSummary | None


class OverviewOut(BaseModel):
    items: list[OverviewRow]
    total: int
    limit: int
    offset: int


class Capability(BaseModel):
    key: str
    label: str
    status: Literal["enabled", "disabled", "not_configured", "not_implemented"]
    requires_external: bool
    detail: str


class CapabilitiesOut(BaseModel):
    engine_version: str
    capabilities: list[Capability]
    trust_material: dict[str, Any]
    registries: list[dict[str, Any]]
    statement: str
