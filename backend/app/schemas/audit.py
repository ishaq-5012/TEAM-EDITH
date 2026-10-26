from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.common import ORMModel


class AuditEventOut(ORMModel):
    id: str
    seq: int
    occurred_at: datetime
    actor_id: str | None
    actor_email: str | None
    action: str
    entity_type: str | None
    entity_id: str | None
    outcome: str
    summary: str
    data: dict[str, Any]
    request_id: str | None
    prev_hash: str
    entry_hash: str


class ChainVerificationOut(BaseModel):
    valid: bool
    checked: int
    first_invalid_seq: int | None
    reason: str | None
    head_hash: str | None
