"""Role restrictions, cross-user access and user administration."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.errors import ConflictError, DomainError
from app.core.roles import ROLE_PERMISSIONS, Permission, Role
from app.models.audit import AuditEvent
from app.services import user_service
from app.services.audit_service import AuditContext

API = "/api/v1"
NEW_USER = {
    "email": "new.person@example.org",
    "full_name": "New Person",
    "role": "reviewer",
    "password": "Valid-Passw0rd!",
}

# (method, path, body, permission) for every protected, role-gated endpoint.
GATED = [
    ("GET", "/users", None, Permission.USERS_READ),
    ("POST", "/users", NEW_USER, Permission.USERS_MANAGE),
    ("GET", "/audit/events", None, Permission.AUDIT_READ),
    ("GET", "/audit/verify", None, Permission.AUDIT_READ),
    ("GET", "/system/capabilities", None, Permission.SYSTEM_READ),
]


def test_exactly_five_roles():
    assert {r.value for r in Role} == {
        "admin", "compliance_manager", "second_approver", "reviewer", "auditor"
    }
    assert Permission.RULES_PUBLISH not in ROLE_PERMISSIONS[Role.ADMIN]
    assert Permission.RULES_PUBLISH not in ROLE_PERMISSIONS[Role.COMPLIANCE_MANAGER]
    assert Permission.RULES_PUBLISH in ROLE_PERMISSIONS[Role.SECOND_APPROVER]
    assert Permission.RULES_MANAGE not in ROLE_PERMISSIONS[Role.SECOND_APPROVER]


def test_auditor_is_read_only():
    write_actions = {"manage", "write", "upload", "publish", "run", "resolve"}
    writes = {p for p in Permission if p.value.split(":")[1] in write_actions}
    assert not (ROLE_PERMISSIONS[Role.AUDITOR] & writes)


@pytest.mark.parametrize("role", list(Role))
@pytest.mark.parametrize("method,path,body,permission", GATED)
def test_role_matrix_enforced_by_backend(auth_as, role, method, path, body, permission):
    c = auth_as(role)
    r = c.request(method, f"{API}{path}", json=body)
    if permission in ROLE_PERMISSIONS[role]:
        assert r.status_code in (200, 201), (role, path, r.text)
    else:
        assert r.status_code == 403, (role, path, r.status_code)
        assert r.json()["error"]["code"] == "forbidden"


@pytest.mark.parametrize("method,path,body,_", GATED)
def test_anonymous_is_rejected_everywhere(client, method, path, body, _):
    assert client.request(method, f"{API}{path}", json=body).status_code == 401


def test_permission_denial_is_audited(auth_as, db):
    c = auth_as(Role.REVIEWER)
    c.post(f"{API}/users", json=NEW_USER)
    ev = db.execute(select(AuditEvent).where(AuditEvent.action == "security.permission_denied")).scalar_one()
    assert ev.data["permission"] == "users:manage"
    assert ev.actor_email == "reviewer@example.org"


# ------------------------------------------------------------------ cross-user access


def test_user_can_read_own_record_but_not_others(make_user, login):
    alice = make_user(Role.REVIEWER, email="alice@example.org")
    bob = make_user(Role.REVIEWER, email="bob@example.org")
    a = login(alice.email)
    assert a.get(f"{API}/users/{alice.id}").status_code == 200
    assert a.get(f"{API}/users/{bob.id}").status_code == 404  # 404, not 403: existence is not confirmed
    assert a.get(f"{API}/users/does-not-exist").status_code == 404


def test_user_cannot_revoke_another_users_session(make_user, login):
    alice = make_user(Role.REVIEWER, email="alice@example.org")
    bob = make_user(Role.COMPLIANCE_MANAGER, email="bob@example.org")
    a = login(alice.email)
    b = login(bob.email)
    bob_session = b.get(f"{API}/auth/sessions").json()[0]["id"]
    assert a.delete(f"{API}/auth/sessions/{bob_session}").status_code == 404
    assert b.get(f"{API}/auth/me").status_code == 200


def test_own_session_list_never_includes_other_users(make_user, login):
    alice = make_user(Role.REVIEWER, email="alice@example.org")
    bob = make_user(Role.REVIEWER, email="bob@example.org")
    a = login(alice.email)
    login(bob.email)
    login(bob.email)
    assert len(a.get(f"{API}/auth/sessions").json()) == 1


def test_admin_can_inspect_and_revoke_other_users_sessions(make_user, login, auth_as):
    admin = auth_as(Role.ADMIN)
    target = make_user(Role.REVIEWER)
    t = login(target.email)
    assert len(admin.get(f"{API}/users/{target.id}/sessions").json()) == 1
    r = admin.post(f"{API}/users/{target.id}/revoke-sessions", json={"reason": "suspicious activity"})
    assert r.json() == {"revoked": 1}
    assert t.get(f"{API}/auth/me").status_code == 401


@pytest.mark.parametrize("role", [Role.COMPLIANCE_MANAGER, Role.SECOND_APPROVER, Role.REVIEWER, Role.AUDITOR])
def test_non_admins_cannot_manage_others_sessions(make_user, auth_as, role):
    target = make_user(Role.REVIEWER, email="target@example.org")
    c = auth_as(role)
    assert c.get(f"{API}/users/{target.id}/sessions").status_code == 403
    assert c.post(f"{API}/users/{target.id}/revoke-sessions", json={"reason": "nope"}).status_code == 403


# ------------------------------------------------------------------ administration


def test_admin_creates_user_and_duplicate_conflicts(auth_as):
    admin = auth_as(Role.ADMIN)
    r = admin.post(f"{API}/users", json=NEW_USER)
    assert r.status_code == 201, r.text
    assert r.json()["role"] == "reviewer"
    assert admin.post(f"{API}/users", json={**NEW_USER, "email": "NEW.person@example.org"}).status_code == 409


def test_create_user_validates_input(auth_as):
    admin = auth_as(Role.ADMIN)
    for bad in ({"role": "analyst"}, {"role": "superuser"}, {"email": "not-an-email"}, {"password": "weakpass"}):
        assert admin.post(f"{API}/users", json={**NEW_USER, **bad}).status_code == 422, bad


def test_role_change_ends_sessions_immediately(make_user, login, auth_as):
    admin = auth_as(Role.ADMIN)
    target = make_user(Role.COMPLIANCE_MANAGER)
    t = login(target.email)
    assert t.get(f"{API}/audit/events").status_code == 200
    admin.patch(f"{API}/users/{target.id}", json={"role": "reviewer", "reason": "change of duties"})
    assert t.get(f"{API}/audit/events").status_code == 401
    assert login(target.email).get(f"{API}/audit/events").status_code == 403


def test_cannot_remove_last_admin(make_user, login):
    admin = make_user(Role.ADMIN)
    c = login(admin.email)
    assert c.patch(f"{API}/users/{admin.id}", json={"role": "reviewer", "reason": "demote"}).status_code == 409


def test_update_requires_reason(auth_as, make_user):
    admin = auth_as(Role.ADMIN)
    target = make_user(Role.REVIEWER)
    assert admin.patch(f"{API}/users/{target.id}", json={"role": "auditor"}).status_code == 422


def test_update_is_audited_with_before_after(auth_as, make_user):
    admin = auth_as(Role.ADMIN)
    target = make_user(Role.REVIEWER)
    admin.patch(f"{API}/users/{target.id}", json={"role": "auditor", "reason": "rotation"})
    events = admin.get(f"{API}/audit/events", params={"action": "user.updated"}).json()
    assert events["total"] == 1
    data = events["items"][0]["data"]
    assert data["before"]["role"] == "reviewer" and data["after"]["role"] == "auditor"
    assert data["reason"] == "rotation"
    assert events["items"][0]["actor_email"] == "admin@example.org"


def test_service_rejects_reserved_email_domain_on_every_path(db):
    with pytest.raises(DomainError) as exc:
        user_service.create_user(
            db, AuditContext(), email="admin@corp.local", full_name="X", role=Role.ADMIN, password="Valid-Passw0rd!"
        )
    assert exc.value.code == "invalid_email"


# ------------------------------------------------------------------ development bootstrap


def _as_env(monkeypatch, env: str) -> None:
    from app.core.config import get_settings

    settings = get_settings().model_copy(update={"environment": env})
    monkeypatch.setattr(user_service, "get_settings", lambda: settings)


def test_bootstrap_dev_admin_creates_admin_with_one_time_password(db, monkeypatch, client):
    _as_env(monkeypatch, "development")
    user, password = user_service.bootstrap_dev_admin(db, AuditContext(), email="first@example.com", full_name="First")
    assert user.role == "admin"
    assert password not in user.password_hash
    r = client.post(f"{API}/auth/login", json={"email": "first@example.com", "password": password})
    assert r.status_code == 200


@pytest.mark.parametrize("env", ["production", "test"])
def test_bootstrap_refused_outside_development(db, monkeypatch, env):
    _as_env(monkeypatch, env)
    with pytest.raises(DomainError) as exc:
        user_service.bootstrap_dev_admin(db, AuditContext(), email="first@example.com", full_name="First")
    assert exc.value.code == "not_development"


def test_bootstrap_refused_once_users_exist(db, monkeypatch, make_user):
    _as_env(monkeypatch, "development")
    make_user(Role.AUDITOR)
    with pytest.raises(ConflictError):
        user_service.bootstrap_dev_admin(db, AuditContext(), email="first@example.com", full_name="First")
