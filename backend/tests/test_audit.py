from __future__ import annotations

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError

from app.core.roles import Role
from app.models.audit import AuditEvent, AuditImmutableError
from app.services import audit_service
from app.services.audit_service import AuditContext

API = "/api/v1"


def test_chain_valid_after_activity(auth_as):
    r = auth_as(Role.AUDITOR).get(f"{API}/audit/verify")
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is True
    assert body["checked"] >= 2  # user.created + auth.login


def test_orm_blocks_update_and_delete(db):
    audit_service.record(db, AuditContext(), "test.event", data={"k": 1})
    db.commit()
    ev = db.execute(select(AuditEvent)).scalar_one()
    ev.summary = "changed"
    with pytest.raises(AuditImmutableError):
        db.flush()
    db.rollback()
    db.delete(db.execute(select(AuditEvent)).scalar_one())
    with pytest.raises(AuditImmutableError):
        db.flush()
    db.rollback()


def test_database_trigger_blocks_raw_sql_mutation(db):
    audit_service.record(db, AuditContext(), "test.event")
    db.commit()
    with pytest.raises(DatabaseError):
        db.execute(text("UPDATE audit_events SET summary = 'x'"))
    db.rollback()
    with pytest.raises(DatabaseError):
        db.execute(text("DELETE FROM audit_events"))
    db.rollback()


def _bypass_append_only_trigger(db, kind: str) -> None:  # noqa: ANN001
    """What an attacker with raw database access would do first: switch off the append-only protection."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("ALTER TABLE audit_events DISABLE TRIGGER audit_events_no_mutation"))
    else:
        db.execute(text(f"DROP TRIGGER audit_events_no_{kind}"))


def test_verify_detects_tampering(db):
    for i in range(3):
        audit_service.record(db, AuditContext(), "test.event", data={"i": i})
    db.commit()
    assert audit_service.verify_chain(db).valid
    # Simulate an attacker with raw DB access: drop the trigger, then alter a row.
    _bypass_append_only_trigger(db, "update")
    db.execute(text("UPDATE audit_events SET data = '{\"i\": 99}' WHERE seq = 2"))
    db.commit()
    db.expire_all()
    result = audit_service.verify_chain(db)
    assert result.valid is False
    assert result.first_invalid_seq == 2


def test_concurrent_appends_serialize_without_conflicts(session_factory):
    """Regression: parallel writers used to read the same head and collide on seq (HTTP 500)."""
    import threading

    errors: list[BaseException] = []
    start = threading.Barrier(8)

    def writer(n: int) -> None:
        try:
            start.wait()
            for i in range(5):
                with session_factory() as s:
                    audit_service.record(s, AuditContext(), "test.concurrent", data={"writer": n, "i": i})
                    s.commit()
        except BaseException as exc:  # noqa: BLE001 - collected and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    with session_factory() as s:
        result = audit_service.verify_chain(s)
        assert result.valid, result
        assert result.checked == 40


def test_verify_detects_removed_tail_via_head(db):
    for i in range(3):
        audit_service.record(db, AuditContext(), "test.event", data={"i": i})
    db.commit()
    _bypass_append_only_trigger(db, "delete")
    db.execute(text("DELETE FROM audit_events WHERE seq = 3"))
    db.commit()
    result = audit_service.verify_chain(db)
    assert result.valid is False
    assert "head" in result.reason
