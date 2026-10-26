from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import false, func, or_, select, update
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models.audit import AuditEvent, AuditHead
from app.models.user import User

GENESIS_HASH = "0" * 64


@dataclass(frozen=True)
class AuditContext:
    """Request metadata captured with each event."""

    actor: User | None = None
    request_id: str | None = None
    ip_address: str | None = None


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="microseconds")


def compute_hash(prev_hash: str, ev: AuditEvent) -> str:
    material = {
        "seq": ev.seq,
        "occurred_at": _iso(ev.occurred_at),
        "actor_id": ev.actor_id,
        "actor_email": ev.actor_email,
        "action": ev.action,
        "entity_type": ev.entity_type,
        "entity_id": ev.entity_id,
        "outcome": ev.outcome,
        "summary": ev.summary,
        "data": ev.data,
        "request_id": ev.request_id,
        "ip_address": ev.ip_address,
    }
    return hashlib.sha256((prev_hash + _canonical(material)).encode("utf-8")).hexdigest()


def record(
    db: Session,
    ctx: AuditContext,
    action: str,
    *,
    entity_type: str | None = None,
    entity_id: str | None = None,
    summary: str = "",
    data: dict[str, Any] | None = None,
    outcome: str = "success",
    actor_override: User | None = None,
) -> AuditEvent:
    """Append an event to the chain. Caller owns the transaction (commit together with the change).

    Concurrency: the head row is claimed with an UPDATE first, which blocks other appenders until
    this transaction commits or rolls back, so sequence numbers and hashes can't race.
    """
    actor = actor_override or ctx.actor
    seq, prev_hash = _claim_next(db)
    ev = AuditEvent(
        seq=seq,
        occurred_at=utcnow(),
        actor_id=actor.id if actor else None,
        actor_email=actor.email if actor else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        outcome=outcome,
        summary=summary,
        # Round-trip through JSON so the stored value hashes identically when re-read.
        data=json.loads(_canonical(data or {})),
        request_id=ctx.request_id,
        ip_address=ctx.ip_address,
        prev_hash=prev_hash,
    )
    ev.entry_hash = compute_hash(prev_hash, ev)
    db.execute(update(AuditHead).where(AuditHead.id == HEAD_ID).values(last_hash=ev.entry_hash))
    db.add(ev)
    db.flush()
    return ev


HEAD_ID = 1


def _claim_next(db: Session) -> tuple[int, str]:
    """Atomically take the next sequence number; returns (seq, previous entry hash)."""
    stmt = (
        update(AuditHead)
        .where(AuditHead.id == HEAD_ID)
        .values(seq=AuditHead.seq + 1)
        .returning(AuditHead.seq, AuditHead.last_hash)
        .execution_options(synchronize_session=False)
    )
    row = db.execute(stmt).one_or_none()
    if row is None:
        raise RuntimeError("audit_head row is missing; run database migrations (alembic upgrade head)")
    return row.seq, row.last_hash


@dataclass
class ChainVerification:
    valid: bool
    checked: int
    first_invalid_seq: int | None
    reason: str | None
    head_hash: str | None


def verify_chain(db: Session) -> ChainVerification:
    prev = GENESIS_HASH
    expected_seq = 1
    checked = 0
    for ev in db.execute(select(AuditEvent).order_by(AuditEvent.seq)).scalars():
        if ev.seq != expected_seq:
            return ChainVerification(False, checked, ev.seq, f"Sequence gap: expected {expected_seq}", prev)
        if ev.prev_hash != prev:
            return ChainVerification(False, checked, ev.seq, "prev_hash does not match previous entry", prev)
        if compute_hash(prev, ev) != ev.entry_hash:
            return ChainVerification(False, checked, ev.seq, "entry_hash mismatch (content altered)", prev)
        prev = ev.entry_hash
        expected_seq += 1
        checked += 1
    head = db.get(AuditHead, HEAD_ID)
    if head is not None and (head.seq != checked or head.last_hash != (prev if checked else GENESIS_HASH)):
        return ChainVerification(
            False, checked, head.seq, "Chain head does not match the last event (events removed or head altered)", prev
        )
    return ChainVerification(True, checked, None, None, prev if checked else None)


def institution_scope(user: User):  # noqa: ANN201
    """Filter limiting audit reads to events caused by people in the reader's institution.

    The hash chain itself stays global (one chain proves one history); this only limits what each institution can
    read. System events about an application (document processing) follow the application's institution. Events with
    no actor and no application (for example a failed sign-in for an unknown email) are not shown to any institution.
    """
    if not user.institution_id:
        return false()
    from app.models.application import Application  # local import: models.application imports services indirectly

    people = select(User.id).where(User.institution_id == user.institution_id)
    cases = select(Application.id).where(Application.institution_id == user.institution_id)
    # Caused by someone in the institution, or a system event about one of its applications (document processing).
    return or_(AuditEvent.actor_id.in_(people), (AuditEvent.entity_type == "application") & AuditEvent.entity_id.in_(cases))


def count(db: Session) -> int:
    return db.execute(select(func.count()).select_from(AuditEvent)).scalar_one()
