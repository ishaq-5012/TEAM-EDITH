from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    database: Literal["ok", "error"]
    version: str


class ProcessingHealthOut(BaseModel):
    mode: Literal["inline", "worker"]
    queued: int
    oldest_queued_seconds: int | None
    stale_running: int


class ReadinessOut(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    database: Literal["ok", "error"]
    migrations: Literal["ok", "behind", "error"]
    storage: Literal["ok", "error"]
    processing: ProcessingHealthOut | None


class CapabilityOut(BaseModel):
    key: str
    label: str
    available: bool
    detail: str


class CapabilitiesOut(BaseModel):
    environment: str
    version: str
    ai_provider_configured: str
    ai_provider_active: str
    ai_enabled: bool
    capabilities: list[CapabilityOut]
