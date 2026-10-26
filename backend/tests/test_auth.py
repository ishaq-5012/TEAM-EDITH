"""Authentication, cookie sessions, expiry, CSRF and throttling."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.roles import Role
from app.db.base import utcnow
from app.models.audit import AuditEvent
from app.models.session import UserSession
from tests.conftest import PASSWORD

API = "/api/v1"
SESSION_COOKIE = get_settings().session_cookie_name
CSRF_COOKIE = get_settings().csrf_cookie_name


def _login(c, email: str, password: str):  # noqa: ANN001, ANN202
    return c.post(f"{API}/auth/login", json={"email": email, "password": password})


def _set_cookie_headers(response) -> dict[str, str]:  # noqa: ANN001
    out = {}
    for raw in response.headers.get_list("set-cookie"):
        name = raw.split("=", 1)[0]
        out[name] = raw.lower()
    return out


# ------------------------------------------------------------------ login / cookies


def test_login_sets_hardened_cookies_and_returns_profile(client, make_user):
    user = make_user(Role.REVIEWER, email="Rae@Example.org")
    r = client.post(f"{API}/auth/login", json={"email": "rae@example.org", "password": PASSWORD})
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["id"] == user.id
    assert body["user"]["role"] == "reviewer"
    assert body["user"]["session"]["idle_timeout_minutes"] == get_settings().session_idle_minutes
    assert "password_hash" not in body["user"]
    assert body["csrf_token"]

    cookies = _set_cookie_headers(r)
    session = cookies[SESSION_COOKIE]
    assert "httponly" in session and "secure" in session and "samesite=lax" in session and "path=/" in session
    csrf = cookies[CSRF_COOKIE]
    assert "httponly" not in csrf and "secure" in csrf and "samesite=strict" in csrf
    assert SESSION_COOKIE.startswith("__Host-")


def test_session_token_is_stored_only_as_hash(client, make_user, db):
    make_user(Role.REVIEWER)
    r = client.post(f"{API}/auth/login", json={"email": "reviewer@example.org", "password": PASSWORD})
    raw = r.cookies.get(SESSION_COOKIE)
    stored = db.execute(select(UserSession)).scalar_one()
    assert raw and stored.token_hash != raw and len(stored.token_hash) == 64
    assert stored.csrf_hash != r.json()["csrf_token"]


def test_me_requires_session_cookie(client):
    r = client.get(f"{API}/auth/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


def test_bearer_headers_are_not_accepted(client):
    r = client.get(f"{API}/auth/me", headers={"Authorization": "Bearer anything"})
    assert r.status_code == 401


# ------------------------------------------------------------------ invalid credentials / inactive


@pytest.mark.parametrize("case", ["wrong_password", "unknown_account", "inactive_account"])
def test_failures_are_indistinguishable(client, make_user, case):
    make_user(Role.REVIEWER, email="known@example.org", active=case != "inactive_account")
    email = "ghost@example.org" if case == "unknown_account" else "known@example.org"
    password = "Not-The-Password-1" if case == "wrong_password" else PASSWORD
    r = client.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert r.status_code == 401
    assert r.json()["error"] == {"code": "invalid_credentials", "message": "Invalid email or password", "details": None}
    assert SESSION_COOKIE not in r.cookies


def test_failed_login_audits_reason_without_password(client, make_user, db):
    make_user(Role.REVIEWER, active=False)
    client.post(f"{API}/auth/login", json={"email": "reviewer@example.org", "password": PASSWORD})
    ev = db.execute(select(AuditEvent).where(AuditEvent.action == "auth.login_failed")).scalar_one()
    assert ev.data["reason"] == "inactive_account"
    assert PASSWORD not in str(ev.data)


def test_deactivating_user_ends_live_sessions(make_user, login, auth_as):
    admin = auth_as(Role.ADMIN)
    target = make_user(Role.REVIEWER)
    c = login(target.email)
    assert c.get(f"{API}/auth/me").status_code == 200
    r = admin.patch(f"{API}/users/{target.id}", json={"is_active": False, "reason": "left the team"})
    assert r.status_code == 200
    r = c.get(f"{API}/auth/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "session_expired"


# ------------------------------------------------------------------ logout / session expiry


def test_logout_revokes_server_session_and_clears_cookies(login, make_user, client_factory):
    make_user(Role.AUDITOR)
    c = login("auditor@example.org")
    stolen_cookie = c.cookies.get(SESSION_COOKIE)
    r = c.post(f"{API}/auth/logout")
    assert r.status_code == 204
    cleared = _set_cookie_headers(r)
    assert 'max-age=0' in cleared[SESSION_COOKIE] or "expires=" in cleared[SESSION_COOKIE]
    # Replaying the old cookie from another client must fail: revocation is server-side.
    attacker = client_factory()
    attacker.cookies.set(SESSION_COOKIE, stolen_cookie)
    assert attacker.get(f"{API}/auth/me").status_code == 401


@pytest.mark.parametrize("field", ["idle_expires_at", "expires_at"])
def test_expired_session_is_rejected(login, make_user, session_factory, field):
    make_user(Role.REVIEWER)
    c = login("reviewer@example.org")
    with session_factory() as s:
        s.execute(update(UserSession).values({field: utcnow() - timedelta(seconds=1)}))
        s.commit()
    r = c.get(f"{API}/auth/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "session_expired"
    with session_factory() as s:
        assert s.execute(select(UserSession.revoked_reason)).scalar_one() == "expired"


def test_activity_slides_idle_window_but_never_past_absolute(login, make_user, session_factory):
    make_user(Role.REVIEWER)
    c = login("reviewer@example.org")
    absolute = utcnow() + timedelta(minutes=5)
    with session_factory() as s:
        s.execute(
            update(UserSession).values(
                last_seen_at=utcnow() - timedelta(minutes=10),
                idle_expires_at=utcnow() + timedelta(minutes=1),
                expires_at=absolute,
            )
        )
        s.commit()
    r = c.get(f"{API}/auth/me")
    assert r.status_code == 200
    assert r.headers["X-Session-Expires"]
    with session_factory() as s:
        sess = s.execute(select(UserSession)).scalar_one()
        assert sess.idle_expires_at == sess.expires_at  # capped at the absolute expiry


def test_change_password_keeps_current_session_and_revokes_others(make_user, login):
    make_user(Role.REVIEWER)
    first = login("reviewer@example.org")
    second = login("reviewer@example.org")
    r = first.post(
        f"{API}/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "An0ther-Strong-Pass"},
    )
    assert r.status_code == 204
    assert first.get(f"{API}/auth/me").status_code == 200
    assert second.get(f"{API}/auth/me").status_code == 401
    login("reviewer@example.org", "An0ther-Strong-Pass")


def test_wrong_current_password_does_not_sign_out(make_user, login):
    make_user(Role.REVIEWER)
    c = login("reviewer@example.org")
    body = {"current_password": "Wrong-Pass-123", "new_password": "An0ther-Strong-Pass"}
    r = c.post(f"{API}/auth/change-password", json=body)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "wrong_current_password"
    assert c.get(f"{API}/auth/me").status_code == 200


def test_list_and_revoke_own_sessions(make_user, login):
    make_user(Role.REVIEWER)
    a = login("reviewer@example.org")
    b = login("reviewer@example.org")
    sessions = a.get(f"{API}/auth/sessions").json()
    assert len(sessions) == 2
    assert sum(s["current"] for s in sessions) == 1
    other = next(s for s in sessions if not s["current"])
    assert a.delete(f"{API}/auth/sessions/{other['id']}").status_code == 204
    assert b.get(f"{API}/auth/me").status_code == 401
    assert a.get(f"{API}/auth/me").status_code == 200


def test_revoke_others(make_user, login):
    make_user(Role.REVIEWER)
    a = login("reviewer@example.org")
    b = login("reviewer@example.org")
    c = login("reviewer@example.org")
    assert a.post(f"{API}/auth/sessions/revoke-others").json() == {"revoked": 2}
    assert b.get(f"{API}/auth/me").status_code == 401 and c.get(f"{API}/auth/me").status_code == 401
    assert a.get(f"{API}/auth/me").status_code == 200


# ------------------------------------------------------------------ CSRF


def test_state_change_without_csrf_header_is_rejected_and_audited(make_user, login, db):
    make_user(Role.REVIEWER)
    c = login("reviewer@example.org")
    del c.headers["X-CSRF-Token"]
    r = c.post(f"{API}/auth/logout")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "csrf_failed"
    assert c.get(f"{API}/auth/me").status_code == 200  # session still alive: logout did not happen
    assert db.execute(select(AuditEvent).where(AuditEvent.action == "security.csrf_rejected")).scalar_one()


def test_csrf_token_from_another_session_is_rejected(make_user, login):
    make_user(Role.REVIEWER)
    make_user(Role.AUDITOR)
    victim = login("reviewer@example.org")
    attacker = login("auditor@example.org")
    victim.headers["X-CSRF-Token"] = attacker.headers["X-CSRF-Token"]
    assert victim.post(f"{API}/auth/logout").status_code == 403


def test_forged_csrf_cookie_does_not_help(make_user, login):
    """Double-submit with an attacker-chosen value fails: the server checks the session's stored hash."""
    make_user(Role.REVIEWER)
    c = login("reviewer@example.org")
    c.cookies.set(CSRF_COOKIE, "attacker-chosen")
    c.headers["X-CSRF-Token"] = "attacker-chosen"
    assert c.post(f"{API}/auth/logout").status_code == 403


def test_safe_methods_do_not_need_csrf(make_user, login):
    make_user(Role.REVIEWER)
    c = login("reviewer@example.org")
    del c.headers["X-CSRF-Token"]
    assert c.get(f"{API}/auth/me").status_code == 200


@pytest.mark.parametrize("path", ["/auth/login", "/auth/logout"])
def test_cross_site_origin_is_rejected(client, make_user, path):
    make_user(Role.REVIEWER)
    r = client.post(
        f"{API}{path}",
        json={"email": "reviewer@example.org", "password": PASSWORD},
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "origin_rejected"


def test_allowed_and_same_origin_pass_origin_check(client, make_user):
    make_user(Role.REVIEWER)
    for origin in ("http://localhost:5173", "https://testserver"):
        r = client.post(
            f"{API}/auth/login",
            json={"email": "reviewer@example.org", "password": PASSWORD},
            headers={"Origin": origin},
        )
        assert r.status_code == 200, origin


# ------------------------------------------------------------------ throttling


def test_email_throttle_applies_even_with_correct_password(client, make_user):
    make_user(Role.REVIEWER)
    for _ in range(get_settings().login_max_failures):
        assert _login(client, "reviewer@example.org", "nope").status_code == 401
    r = client.post(f"{API}/auth/login", json={"email": "reviewer@example.org", "password": PASSWORD})
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "too_many_attempts"


def test_throttle_is_identical_for_unknown_accounts(client):
    """No enumeration: an unknown email throttles exactly like a real one."""
    for _ in range(get_settings().login_max_failures):
        client.post(f"{API}/auth/login", json={"email": "ghost@example.org", "password": "nope"})
    assert client.post(f"{API}/auth/login", json={"email": "ghost@example.org", "password": "nope"}).status_code == 429


def test_success_resets_email_failure_count(client, make_user):
    make_user(Role.REVIEWER)
    limit = get_settings().login_max_failures
    for _ in range(limit - 1):
        client.post(f"{API}/auth/login", json={"email": "reviewer@example.org", "password": "nope"})
    assert _login(client, "reviewer@example.org", PASSWORD).status_code == 200
    for _ in range(limit - 1):
        client.post(f"{API}/auth/login", json={"email": "reviewer@example.org", "password": "nope"})
    assert _login(client, "reviewer@example.org", PASSWORD).status_code == 200


def test_ip_throttle_across_many_emails(client):
    limit = get_settings().login_ip_max_failures
    for i in range(limit):
        client.post(f"{API}/auth/login", json={"email": f"spray{i}@example.org", "password": "nope"})
    r = client.post(f"{API}/auth/login", json={"email": "fresh@example.org", "password": "nope"})
    assert r.status_code == 429


def test_admin_password_reset_clears_throttle(client, make_user, auth_as):
    target = make_user(Role.REVIEWER)
    for _ in range(get_settings().login_max_failures):
        client.post(f"{API}/auth/login", json={"email": target.email, "password": "nope"})
    admin = auth_as(Role.ADMIN)
    body = {"new_password": "Fresh-Pass-2026!", "reason": "locked out"}
    r = admin.post(f"{API}/users/{target.id}/reset-password", json=body)
    assert r.status_code == 204
    assert _login(client, target.email, "Fresh-Pass-2026!").status_code == 200


def test_retention_prunes_only_sessions_that_ended_long_ago(make_user, login, session_factory):
    from datetime import timedelta

    from sqlalchemy import func, select, update

    from app.db.base import utcnow
    from app.models import AuditEvent
    from app.models.session import UserSession
    from app.services import session_service
    from app.services.audit_service import AuditContext

    user = make_user(Role.REVIEWER, email="keeper@example.org")
    live = login(user.email)
    for _ in range(3):
        login(user.email)
    old = utcnow() - timedelta(days=200)
    with session_factory() as s:
        ids = [r for r in s.execute(select(UserSession.id).order_by(UserSession.created_at)).scalars()]
        s.execute(update(UserSession).where(UserSession.id == ids[1]).values(revoked_at=old))  # revoked long ago
        s.execute(update(UserSession).where(UserSession.id == ids[2]).values(expires_at=old))  # expired long ago
        s.execute(  # revoked yesterday: within the retention window
            update(UserSession).where(UserSession.id == ids[3]).values(revoked_at=utcnow() - timedelta(days=1))
        )
        s.commit()
        assert session_service.prune_ended(s, AuditContext(request_id="test"), 90) == 2
        assert set(s.execute(select(UserSession.id)).scalars()) == {ids[0], ids[3]}
        assert s.execute(
            select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "session.retention_pruned")
        ).scalar_one() == 1
    assert live.get(f"{API}/auth/me").status_code == 200
