"""Institution isolation: roles say what a person may do, the institution says whose records they may do it to.

Two synthetic institutions; nothing here is real data. Every cross-institution attempt must look like "not found",
for every role including administrators and auditors.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.core.errors import ConflictError, DomainError
from app.core.roles import Role
from app.models import Application, User
from app.services import institution_service
from app.services.audit_service import AuditContext
from tests import factories

API = "/api/v1"


@pytest.fixture
def two_institutions(make_user, make_institution, login):
    """Institution A (the default) and B, each with an admin, a reviewer and an auditor."""
    b = make_institution()
    people = {}
    for name, role in (("admin", Role.ADMIN), ("manager", Role.COMPLIANCE_MANAGER), ("reviewer", Role.REVIEWER), ("auditor", Role.AUDITOR)):
        make_user(role, email=f"{name}-a@example.org")
        make_user(role, email=f"{name}-b@example.org", institution_id=b)
        people[f"{name}_a"] = login(f"{name}-a@example.org")
        people[f"{name}_b"] = login(f"{name}-b@example.org")
    return people


def _case(c) -> dict:  # noqa: ANN001
    r = c.post(f"{API}/applications", json={"title": "Synthetic isolation case", "application_type": "kyc"})
    assert r.status_code == 201, r.text
    return r.json()


def _upload(c, app_id: str):  # noqa: ANN001, ANN201
    pdf = factories.labelled_pdf([["Full name: Test Person Alpha", "Date of birth: 03 March 1990"]])
    return c.post(f"{API}/applications/{app_id}/documents", files={"file": ("synthetic.pdf", pdf, "application/pdf")})


@pytest.mark.parametrize("who", ["admin_b", "manager_b", "reviewer_b", "auditor_b"])
def test_no_role_can_read_another_institutions_application(two_institutions, who):
    app = _case(two_institutions["reviewer_a"])
    other = two_institutions[who]
    assert other.get(f"{API}/applications/{app['id']}").status_code == 404
    assert other.get(f"{API}/applications/{app['id']}/documents").status_code == 404
    assert other.get(f"{API}/applications/{app['id']}/evidence").status_code == 404
    listed = other.get(f"{API}/applications").json()
    assert app["id"] not in [a["id"] for a in listed["items"]]
    assert listed["total"] == 0


def test_same_institution_oversight_still_works(two_institutions):
    app = _case(two_institutions["reviewer_a"])
    assert two_institutions["manager_a"].get(f"{API}/applications/{app['id']}").status_code == 200
    assert two_institutions["admin_a"].get(f"{API}/applications/{app['id']}").status_code == 200
    assert two_institutions["admin_a"].patch(f"{API}/applications/{app['id']}", json={"title": "Changed"}).status_code == 403
    assert two_institutions["auditor_a"].get(f"{API}/applications/{app['id']}").status_code == 200


def test_cross_institution_edit_upload_and_download_are_not_found(two_institutions):
    app = _case(two_institutions["reviewer_a"])
    doc = _upload(two_institutions["reviewer_a"], app["id"]).json()
    manager_b = two_institutions["manager_b"]
    assert _upload(manager_b, app["id"]).status_code == 404
    assert manager_b.patch(f"{API}/applications/{app['id']}", json={"title": "Hijacked title"}).status_code == 404
    assert manager_b.get(f"{API}/applications/{app['id']}/documents/{doc['id']}/content").status_code == 404
    assert manager_b.get(f"{API}/applications/{app['id']}/documents/{doc['id']}").status_code == 404
    assert manager_b.post(f"{API}/applications/{app['id']}/validation-runs", json={}).status_code == 404
    # The owner's own access is unaffected.
    assert two_institutions["reviewer_a"].get(f"{API}/applications/{app['id']}/documents/{doc['id']}/content").status_code == 200


def test_new_application_belongs_to_the_creators_institution(two_institutions, session_factory):
    app = _case(two_institutions["reviewer_b"])
    with session_factory() as s:
        row = s.get(Application, app["id"])
        creator = s.execute(select(User).where(User.email == "reviewer-b@example.org")).scalar_one()
        assert row.institution_id == creator.institution_id
        assert row.institution_id != institution_service.get_or_create_default(s).id
    assert app["institution"]["code"] == "COLLEGE-B"


def test_cannot_add_another_institutions_user_as_member(two_institutions):
    app = _case(two_institutions["reviewer_a"])
    other = two_institutions["reviewer_a"].post(
        f"{API}/applications/{app['id']}/members", json={"email": "reviewer-b@example.org", "role": "viewer"}
    )
    missing = two_institutions["reviewer_a"].post(
        f"{API}/applications/{app['id']}/members", json={"email": "nobody@example.org", "role": "viewer"}
    )
    # Reported exactly like a missing user, so emails in other institutions cannot be probed.
    assert other.status_code == 404 and missing.status_code == 404
    assert other.json()["error"]["message"] == missing.json()["error"]["message"]


def test_user_administration_stays_inside_the_institution(two_institutions, session_factory):
    admin_a = two_institutions["admin_a"]
    emails = [u["email"] for u in admin_a.get(f"{API}/users").json()["items"]]
    assert emails and all(e.endswith("-a@example.org") for e in emails)
    with session_factory() as s:
        victim = s.execute(select(User).where(User.email == "reviewer-b@example.org")).scalar_one().id
    assert admin_a.get(f"{API}/users/{victim}").status_code == 404
    body = {"is_active": False, "reason": "not allowed"}
    assert admin_a.patch(f"{API}/users/{victim}", json=body).status_code == 404
    reset = {"new_password": "Str0ng-Passw0rd!x", "reason": "attempt"}
    assert admin_a.post(f"{API}/users/{victim}/reset-password", json=reset).status_code == 404
    assert admin_a.get(f"{API}/users/{victim}/sessions").status_code == 404


def test_each_institution_keeps_its_own_last_administrator(two_institutions):
    # Institution B has exactly one admin. Another institution having admins must not let B lose its last one.
    admin_b = two_institutions["admin_b"]
    me = admin_b.get(f"{API}/auth/me").json()
    r = admin_b.patch(f"{API}/users/{me['id']}", json={"is_active": False, "reason": "test last admin"})
    assert r.status_code == 409


def test_audit_trail_is_scoped_to_the_institution(two_institutions):
    _case(two_institutions["reviewer_a"])
    mine = two_institutions["auditor_a"].get(f"{API}/audit/events", params={"action": "application.created"}).json()
    other = two_institutions["auditor_b"].get(f"{API}/audit/events", params={"action": "application.created"}).json()
    assert mine["total"] == 1
    assert other["total"] == 0
    assert "application.created" not in two_institutions["auditor_b"].get(f"{API}/audit/actions").json()


def test_new_users_are_created_inside_the_administrators_institution(two_institutions, session_factory):
    body = {"full_name": "Synthetic New Person", "email": "new.person@example.org", "role": "reviewer",
            "password": "Str0ng-Passw0rd!x"}
    created = two_institutions["admin_b"].post(f"{API}/users", json=body)
    assert created.status_code == 201, created.text
    assert created.json()["institution"]["code"] == "COLLEGE-B"
    listed_b = [u["email"] for u in two_institutions["admin_b"].get(f"{API}/users").json()["items"]]
    listed_a = [u["email"] for u in two_institutions["admin_a"].get(f"{API}/users").json()["items"]]
    assert "new.person@example.org" in listed_b and "new.person@example.org" not in listed_a
    with session_factory() as s:
        row = s.execute(select(User).where(User.email == "new.person@example.org")).scalar_one()
        assert row.institution_id is not None and row.institution.code == "COLLEGE-B"


def test_sign_out_everywhere_is_limited_to_the_institution(two_institutions, session_factory):
    with session_factory() as s:
        victim = s.execute(select(User).where(User.email == "reviewer-b@example.org")).scalar_one().id
    r = two_institutions["admin_a"].post(f"{API}/users/{victim}/revoke-sessions", json={"reason": "not allowed"})
    assert r.status_code == 404
    # The victim's own session is still valid.
    assert two_institutions["reviewer_b"].get(f"{API}/auth/me").status_code == 200
    ok = two_institutions["admin_b"].post(f"{API}/users/{victim}/revoke-sessions", json={"reason": "same institution"})
    assert ok.status_code == 200


def test_system_events_about_an_application_follow_its_institution(two_institutions):
    # Document processing is recorded with no actor; it must still reach the owning institution's auditors.
    app = _case(two_institutions["reviewer_a"])
    assert _upload(two_institutions["reviewer_a"], app["id"]).status_code == 201
    params = {"action": "document.processed"}
    assert two_institutions["auditor_a"].get(f"{API}/audit/events", params=params).json()["total"] == 1
    assert two_institutions["auditor_b"].get(f"{API}/audit/events", params=params).json()["total"] == 0


def test_user_without_an_institution_sees_and_creates_nothing(make_user, login, session_factory):
    user = make_user(Role.REVIEWER, email="orphan@example.org")
    with session_factory() as s:
        s.get(User, user.id).institution_id = None
        s.commit()
    c = login("orphan@example.org")
    r = c.post(f"{API}/applications", json={"title": "Orphan case", "application_type": "kyc"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "no_institution"
    assert c.get(f"{API}/applications").json()["total"] == 0


def test_me_reports_the_institution(two_institutions):
    me = two_institutions["reviewer_b"].get(f"{API}/auth/me").json()
    assert me["institution"]["code"] == "COLLEGE-B"


def test_institution_code_is_validated_and_unique(session_factory):
    with session_factory() as s:
        ctx = AuditContext(request_id="test")
        institution_service.create(s, ctx, name="Synthetic College C", code="college-c")
        with pytest.raises(ConflictError):
            institution_service.create(s, ctx, name="Another College", code="COLLEGE-C")
        with pytest.raises(DomainError):
            institution_service.create(s, ctx, name="Bad Code College", code="bad code!")
        with pytest.raises(DomainError):
            institution_service.create(s, ctx, name="X", code="OKCODE")


def test_every_user_and_application_has_an_institution(two_institutions, session_factory):
    _case(two_institutions["reviewer_a"])
    with session_factory() as s:
        users_without = select(func.count()).select_from(User).where(User.institution_id.is_(None))
        apps_without = select(func.count()).select_from(Application).where(Application.institution_id.is_(None))
        assert s.execute(users_without).scalar_one() == 0
        assert s.execute(apps_without).scalar_one() == 0
