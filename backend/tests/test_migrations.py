"""Migration 0002 converts existing role data and round-trips."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

BACKEND = Path(__file__).resolve().parents[1]
NOW = "2026-01-01 00:00:00.000000"


def _cfg(db: Path) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.attributes["database_url"] = f"sqlite:///{db.as_posix()}"
    return cfg


def test_0002_maps_legacy_roles_and_enforces_constraint(tmp_path):
    db = tmp_path / "m.db"
    cfg = _cfg(db)
    command.upgrade(cfg, "0001_foundation")
    engine = create_engine(f"sqlite:///{db.as_posix()}")
    with engine.begin() as conn:
        for uid, role in (("u1", "compliance_officer"), ("u2", "analyst"), ("u3", "admin"), ("u4", "auditor")):
            conn.execute(
                text(
                    "INSERT INTO users (id, email, full_name, role, password_hash, is_active, token_version, "
                    "failed_login_count, created_at, updated_at) VALUES "
                    "(:id, :email, 'X', :role, 'h', 1, 0, 0, :now, :now)"
                ),
                {"id": uid, "email": f"{uid}@example.org", "role": role, "now": NOW},
            )
    command.upgrade(cfg, "head")
    with engine.begin() as conn:
        roles = dict(conn.execute(text("SELECT id, role FROM users")).all())
    assert roles == {"u1": "compliance_manager", "u2": "reviewer", "u3": "admin", "u4": "auditor"}
    cols = {c["name"] for c in inspect(engine).get_columns("users")}
    assert "token_version" not in cols and "password_changed_at" in cols
    assert {"user_sessions", "login_attempts"} <= set(inspect(engine).get_table_names())

    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(text("UPDATE users SET role = 'superuser' WHERE id = 'u3'"))

    command.downgrade(cfg, "0001_foundation")
    with engine.begin() as conn:
        assert conn.execute(text("SELECT role FROM users WHERE id = 'u1'")).scalar_one() == "compliance_officer"
    command.upgrade(cfg, "head")
    engine.dispose()


def test_batch_rebuilds_never_cascade_into_child_tables(tmp_path):
    """Rebuilding validation_runs (0008 adds lineage columns) must not delete its rule_results through ON DELETE
    CASCADE. Regression test: with foreign-key enforcement on during migrations, SQLite batch mode did exactly that."""
    db = tmp_path / "cascade.db"
    cfg = _cfg(db)
    command.upgrade(cfg, "head")
    engine = create_engine(f"sqlite:///{db.as_posix()}")
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        rows = {
            "users": "INSERT INTO users (id, email, full_name, role, password_hash, is_active, "
            "created_at, updated_at) VALUES ('u1', 'u1@example.org', 'U', 'admin', 'h', 1, :now, :now)",
            "applications": "INSERT INTO applications (id, reference, title, application_type, description, status, "
            "owner_id, created_at, updated_at) VALUES ('a1', 'APP-1', 'T', 'kyc', '', 'draft', 'u1', :now, :now)",
            "rules": "INSERT INTO rules (id, key, name, description, category, owner_id, created_by_id, created_at, "
            "updated_at) VALUES ('r1', 'rule_one', 'Rule', '', 'c', 'u1', 'u1', :now, :now)",
            "rule_versions": "INSERT INTO rule_versions (id, rule_id, version_number, status, definition, "
            "content_hash, "
            "effective_from, source_reference, change_summary, created_by_id, created_at) VALUES ('v1', 'r1', 1, "
            "'published', '{}', 'h', '2026-01-01', 's', 'c', 'u1', :now)",
            "validation_runs": "INSERT INTO validation_runs (id, application_id, evaluation_date, engine_version, "
            "input_snapshot, input_fingerprint, rule_versions, ruleset_fingerprint, summary, created_by_id, "
            "created_at, "
            "trigger, trigger_data) VALUES ('run1', 'a1', '2026-01-01', 'e', '{}', 'f', '[]', 'f', '{}', 'u1', :now, "
            "'manual', '{}')",
            "rule_results": "INSERT INTO rule_results (id, run_id, position, rule_id, rule_version_id, rule_key, "
            "rule_name, "
            "version_number, outcome, severity, reason, message, low_confidence, trace, details) VALUES ('rr1', "
            "'run1', "
            "0, 'r1', 'v1', 'rule_one', 'Rule', 1, 'fail', 'high', 'condition_not_met', '', 0, '[]', '{}')",
        }
        for sql in rows.values():
            conn.execute(text(sql), {"now": NOW})
    engine.dispose()
    command.downgrade(cfg, "0007_rules")
    command.upgrade(cfg, "head")
    engine = create_engine(f"sqlite:///{db.as_posix()}")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM rule_results")).scalar_one() == 1
        assert conn.execute(text("SELECT trigger FROM validation_runs")).scalar_one() == "manual"
    engine.dispose()
