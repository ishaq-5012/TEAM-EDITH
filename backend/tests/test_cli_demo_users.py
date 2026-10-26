"""The development-only `seed-demo-users` command: safe by default, never prints passwords, never overwrites them."""

from __future__ import annotations

import argparse
import re

import pytest
from sqlalchemy import select

from app import cli
from app.core.config import get_settings
from app.models import User

API = "/api/v1"


@pytest.fixture
def dev_cli(monkeypatch, session_factory):
    """Point the CLI at the test database and make it believe this is a development machine."""
    monkeypatch.setattr(cli, "SessionLocal", session_factory)
    settings = get_settings().model_copy(update={"environment": "development"})
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    return session_factory


def _creds(path) -> dict[str, str]:  # noqa: ANN001
    found = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.search(r"(\S+@example\.org)\s+password: (\S+)", line)
        if m:
            found[m.group(1)] = m.group(2)
    return found


def test_refuses_outside_development(monkeypatch, session_factory, tmp_path, capsys):
    monkeypatch.setattr(cli, "SessionLocal", session_factory)  # environment is "test" here
    out = tmp_path / "accounts.txt"
    assert cli.seed_demo_users(argparse.Namespace(out=str(out))) == 1
    assert "development" in capsys.readouterr().err
    assert not out.exists()
    with session_factory() as s:
        assert s.execute(select(User)).first() is None


def test_creates_one_account_per_role_in_two_institutions_without_printing_passwords(dev_cli, tmp_path, capsys, login):
    out = tmp_path / "accounts.txt"
    assert cli.seed_demo_users(argparse.Namespace(out=str(out))) == 0
    creds = _creds(out)
    assert len(creds) == 5
    printed = capsys.readouterr().out
    assert all(pw not in printed for pw in creds.values())

    with dev_cli() as s:
        users = {u.email: u for u in s.execute(select(User)).scalars()}
    assert {u.role for u in users.values()} == {"admin", "compliance_manager", "reviewer", "auditor"}
    assert {u.institution.code for u in users.values()} == {"DEFAULT", "COLLEGE-B"}

    # Every generated password really works, and the strength policy accepted it.
    for email, password in creds.items():
        assert login(email, password).get(f"{API}/auth/me").json()["email"] == email


def test_second_run_adds_nothing_and_keeps_the_passwords(dev_cli, tmp_path):
    out = tmp_path / "accounts.txt"
    assert cli.seed_demo_users(argparse.Namespace(out=str(out))) == 0
    first = out.read_text(encoding="utf-8")
    assert cli.seed_demo_users(argparse.Namespace(out=str(out))) == 0
    assert out.read_text(encoding="utf-8") == first
    with dev_cli() as s:
        assert len(s.execute(select(User)).scalars().all()) == 5


def test_seeded_institutions_are_isolated_from_each_other(dev_cli, tmp_path, login):
    out = tmp_path / "accounts.txt"
    cli.seed_demo_users(argparse.Namespace(out=str(out)))
    creds = _creds(out)
    reviewer_a = login("reviewer.demo@example.org", creds["reviewer.demo@example.org"])
    case = reviewer_a.post(f"{API}/applications", json={"title": "Synthetic seeded case", "application_type": "kyc"}).json()
    admin_b = login("admin.collegeb@example.org", creds["admin.collegeb@example.org"])
    assert admin_b.get(f"{API}/applications/{case['id']}").status_code == 404
    manager = login("compliance.manager@example.org", creds["compliance.manager@example.org"])
    assert manager.get(f"{API}/applications/{case['id']}").status_code == 200
