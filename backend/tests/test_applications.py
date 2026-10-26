"""Applications: creation, listing/filters/pagination, ownership, membership and lifecycle."""

from __future__ import annotations

import re

import pytest

from app.core.roles import Role
from tests import factories

API = "/api/v1"


def new_app(c, title: str = "Synthetic onboarding case", app_type: str = "onboarding", **extra) -> dict:  # noqa: ANN001
    r = c.post(f"{API}/applications", json={"title": title, "application_type": app_type, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def upload(c, app_id: str, content: bytes, name: str = "synthetic.pdf", mime: str = "application/pdf"):  # noqa: ANN001, ANN201
    return c.post(f"{API}/applications/{app_id}/documents", files={"file": (name, content, mime)})


@pytest.fixture
def people(make_user, login):
    """Two reviewers, a compliance manager and an auditor, each signed in on their own client."""
    for email, role in (
        ("alice@example.org", Role.REVIEWER), ("bob@example.org", Role.REVIEWER),
        ("carol@example.org", Role.COMPLIANCE_MANAGER), ("dan@example.org", Role.AUDITOR),
    ):
        make_user(role, email=email)
    return {name: login(f"{name}@example.org") for name in ("alice", "bob", "carol", "dan")}


# ------------------------------------------------------------------ create


def test_create_application(people):
    body = new_app(people["alice"], applicant_name="  Synthetic Applicant  ", description="Test only")
    assert re.fullmatch(r"APP-\d{4}-[2-9A-HJKMNP-Z]{6}", body["reference"])
    assert body["status"] == "draft"
    assert body["owner"]["email"] == "alice@example.org"
    assert body["applicant_name"] == "Synthetic Applicant"
    assert body["permissions"] == {
        "can_edit": True, "can_upload": True, "can_manage_members": True, "allowed_actions": ["archive"],
    }


@pytest.mark.parametrize("payload", [{"title": "x", "application_type": "loan"}, {"title": "Valid title"},
                                     {"title": "Valid title", "application_type": "a" * 61}])
def test_create_validates(people, payload):
    assert people["alice"].post(f"{API}/applications", json=payload).status_code == 422


def test_auditor_cannot_create(people):
    r = people["dan"].post(f"{API}/applications", json={"title": "Nope nope", "application_type": "loan"})
    assert r.status_code == 403


# ------------------------------------------------------------------ list, filters, pagination


def test_list_is_scoped_to_visible_applications(people):
    a1 = new_app(people["alice"], "Alice one")
    a2 = new_app(people["alice"], "Alice two")
    b1 = new_app(people["bob"], "Bob one")

    def refs(c, **params) -> set[str]:  # noqa: ANN001
        return {x["reference"] for x in c.get(f"{API}/applications", params=params).json()["items"]}

    assert refs(people["alice"]) == {a1["reference"], a2["reference"]}
    assert refs(people["bob"]) == {b1["reference"]}
    assert len(refs(people["carol"])) == 3  # applications:read_all
    assert len(refs(people["dan"])) == 3
    assert refs(people["carol"], scope="mine") == set()


def test_filters_search_and_pagination(people):
    c = people["alice"]
    for i in range(7):
        new_app(c, f"Synthetic case {i}", "loan" if i % 2 else "grant", applicant_name=f"Applicant {i}")
    new_app(c, "100% match_test", "loan")

    page1 = c.get(f"{API}/applications", params={"limit": 3, "offset": 0, "sort": "title_asc"}).json()
    page3 = c.get(f"{API}/applications", params={"limit": 3, "offset": 6, "sort": "title_asc"}).json()
    assert page1["total"] == 8 and len(page1["items"]) == 3 and len(page3["items"]) == 2
    assert page1["items"][0]["title"] == "100% match_test"

    loans = c.get(f"{API}/applications", params={"application_type": "loan"}).json()
    assert loans["total"] == 4
    assert set(loans["application_types"]) == {"grant", "loan"}

    # LIKE wildcards in the search term are matched literally.
    assert c.get(f"{API}/applications", params={"q": "%"}).json()["total"] == 1
    assert c.get(f"{API}/applications", params={"q": "_"}).json()["total"] == 1
    assert c.get(f"{API}/applications", params={"q": "applicant 3"}).json()["total"] == 1

    drafts = c.get(f"{API}/applications", params=[("status", "draft"), ("status", "archived")]).json()
    assert drafts["total"] == 8
    assert c.get(f"{API}/applications", params={"status": "bogus"}).status_code == 422
    assert c.get(f"{API}/applications", params={"limit": 101}).status_code == 422


def test_list_reports_document_counts(people):
    app = new_app(people["alice"])
    upload(people["alice"], app["id"], factories.pdf(marker="a"))
    upload(people["alice"], app["id"], factories.png(), "s.png", "image/png")
    item = people["alice"].get(f"{API}/applications").json()["items"][0]
    assert item["document_count"] == 2


# ------------------------------------------------------------------ cross-user access


def test_other_reviewer_cannot_touch_application(people):
    app = new_app(people["alice"])
    doc = upload(people["alice"], app["id"], factories.pdf()).json()
    bob = people["bob"]
    base = f"{API}/applications/{app['id']}"
    assert bob.get(base).status_code == 404
    assert bob.patch(base, json={"title": "Hijacked title"}).status_code == 404
    assert bob.get(f"{base}/documents").status_code == 404
    assert bob.get(f"{base}/documents/{doc['id']}").status_code == 404
    assert bob.get(f"{base}/documents/{doc['id']}/content").status_code == 404
    assert bob.post(f"{base}/documents/{doc['id']}/retry").status_code == 404
    assert upload(bob, app["id"], factories.pdf(marker="bob")).status_code == 404
    assert bob.post(f"{base}/transitions", json={"action": "archive", "reason": "nope"}).status_code == 404
    assert bob.post(f"{base}/members", json={"email": "bob@example.org", "role": "contributor"}).status_code == 404


def test_document_id_from_another_application_is_rejected(people):
    a = new_app(people["alice"], "First case")
    b = new_app(people["alice"], "Second case")
    doc = upload(people["alice"], a["id"], factories.pdf()).json()
    assert people["alice"].get(f"{API}/applications/{b['id']}/documents/{doc['id']}").status_code == 404


def test_auditor_reads_everything_but_changes_nothing(people):
    app = new_app(people["alice"])
    dan = people["dan"]
    detail = dan.get(f"{API}/applications/{app['id']}").json()
    assert detail["permissions"] == {"can_edit": False, "can_upload": False, "can_manage_members": False,
                                     "allowed_actions": []}
    assert dan.patch(f"{API}/applications/{app['id']}", json={"title": "Changed title"}).status_code == 403
    assert upload(dan, app["id"], factories.pdf()).status_code == 403


def test_compliance_manager_can_edit_any_application(people):
    app = new_app(people["alice"])
    r = people["carol"].patch(f"{API}/applications/{app['id']}", json={"title": "Edited by manager"})
    assert r.status_code == 200 and r.json()["title"] == "Edited by manager"


def test_unauthenticated_access_is_rejected(client):
    assert client.get(f"{API}/applications").status_code == 401
    assert client.post(f"{API}/applications", json={"title": "Anon title", "application_type": "x"}).status_code == 401


# ------------------------------------------------------------------ membership


def test_viewer_and_contributor_membership(people):
    alice, bob = people["alice"], people["bob"]
    app = new_app(alice)
    base = f"{API}/applications/{app['id']}"

    assert alice.post(f"{base}/members", json={"email": "bob@example.org", "role": "viewer"}).status_code == 201
    assert bob.get(base).status_code == 200
    assert bob.get(base).json()["permissions"]["can_upload"] is False
    assert bob.patch(base, json={"title": "Viewer edit"}).status_code == 403
    assert upload(bob, app["id"], factories.pdf()).status_code == 403
    assert {x["reference"] for x in bob.get(f"{API}/applications").json()["items"]} == {app["reference"]}

    assert alice.post(f"{base}/members", json={"email": "bob@example.org", "role": "contributor"}).status_code == 201
    assert upload(bob, app["id"], factories.pdf()).status_code == 201
    # Contributors cannot manage membership or archive.
    assert bob.post(f"{base}/members", json={"email": "carol@example.org", "role": "viewer"}).status_code == 403
    assert bob.post(f"{base}/transitions", json={"action": "archive", "reason": "nope"}).status_code == 403

    bob_id = bob.get(f"{API}/auth/me").json()["id"]
    assert alice.delete(f"{base}/members/{bob_id}").status_code == 204
    assert bob.get(base).status_code == 404


@pytest.mark.parametrize("email,role,code", [
    ("ghost@example.org", "viewer", 404),
    ("alice@example.org", "viewer", 409),  # owner
    ("dan@example.org", "contributor", 400),  # auditor is read-only
])
def test_member_validation(people, email, role, code):
    app = new_app(people["alice"])
    r = people["alice"].post(f"{API}/applications/{app['id']}/members", json={"email": email, "role": role})
    assert r.status_code == code, r.text


# ------------------------------------------------------------------ lifecycle


def test_lifecycle_draft_processing_review_complete_archive_restore(people):
    alice = people["alice"]
    app = new_app(alice)
    base = f"{API}/applications/{app['id']}"
    assert alice.post(f"{base}/transitions", json={"action": "complete", "reason": "too early"}).status_code == 409

    assert upload(alice, app["id"], factories.pdf()).status_code == 201
    # Background inspection ran after the response: the application settles into needs_review.
    detail = alice.get(base).json()
    assert detail["status"] == "needs_review"
    assert detail["permissions"]["allowed_actions"] == ["complete", "archive"]

    r = alice.post(f"{base}/transitions", json={"action": "complete", "reason": "all evidence reviewed"})
    assert r.status_code == 200 and r.json()["review_stage"] == "audit"
    assert r.json()["status"] == "needs_review"
    r = people["dan"].post(f"{base}/transitions", json={"action": "approve", "reason": "independent audit confirmed"})
    assert r.status_code == 200 and r.json()["status"] == "completed"
    assert r.json()["review_stage"] == "approved"
    assert upload(alice, app["id"], factories.pdf(marker="late")).json()["error"]["code"] == "application_completed"

    r = alice.post(f"{base}/transitions", json={"action": "archive", "reason": "case closed"})
    assert r.json()["status"] == "archived" and r.json()["archived_at"]
    assert alice.patch(base, json={"title": "Archived edit"}).json()["error"]["code"] == "application_archived"
    assert alice.post(f"{base}/transitions", json={"action": "reopen", "reason": "x" * 3}).status_code == 409

    r = alice.post(f"{base}/transitions", json={"action": "restore", "reason": "appeal received"})
    assert r.json()["status"] == "completed"
    r = people["carol"].post(f"{base}/transitions", json={"action": "reopen", "reason": "new evidence"})
    assert r.json()["status"] == "needs_review"

    events = people["carol"].get(f"{API}/audit/events", params={"entity_id": app["id"], "limit": 100}).json()
    actions = [e["action"] for e in events["items"]]
    for expected in ("application.created", "document.uploaded", "document.processed", "application.sent_to_audit", "application.approved",
                     "application.archived", "application.restored", "application.reopened"):
        assert expected in actions


def test_transition_requires_reason(people):
    app = new_app(people["alice"])
    r = people["alice"].post(f"{API}/applications/{app['id']}/transitions", json={"action": "archive"})
    assert r.status_code == 422


def test_update_records_before_and_after(people):
    app = new_app(people["alice"], "Original title")
    people["alice"].patch(f"{API}/applications/{app['id']}", json={"title": "Better title"})
    ev = people["carol"].get(f"{API}/audit/events", params={"action": "application.updated"}).json()["items"][0]
    assert ev["data"] == {"before": {"title": "Original title"}, "after": {"title": "Better title"}}
    r = people["alice"].patch(f"{API}/applications/{app['id']}", json={"title": "Better title"})
    assert r.json()["error"]["code"] == "no_changes"
