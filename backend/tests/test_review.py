"""Review and Resolution Center: authorization, concurrency, idempotency, corrections, revalidation, history."""

from __future__ import annotations

import pytest
from sqlalchemy import select, text

from app.core.roles import Role
from app.models import AuditEvent, ExtractedField, ReviewAction, ReviewItem, RuleResult, ValidationRun
from app.models.review import ImmutableReviewActionError
from tests import factories

API = "/api/v1"
ADULT = {"field": "extracted.date_of_birth", "op": "age_years_at_least", "value": 18}
ON = "2026-10-23"


@pytest.fixture
def world(make_user, login):
    make_user(Role.ADMIN, email="author@example.org")
    make_user(Role.COMPLIANCE_MANAGER, email="manager@example.org")
    make_user(Role.SECOND_APPROVER, email="approver@example.org")
    make_user(Role.REVIEWER, email="owner@example.org")
    make_user(Role.REVIEWER, email="colleague@example.org")
    make_user(Role.REVIEWER, email="outsider@example.org")
    make_user(Role.AUDITOR, email="auditor@example.org")
    c = {n: login(f"{n}@example.org") for n in ("author", "manager", "approver", "owner", "colleague", "outsider", "auditor")}
    c["ids"] = {n: c[n].get(f"{API}/auth/me").json()["id"] for n in ("owner", "colleague", "outsider", "manager")}
    return c


def publish_rule(c, key="adult_applicant", condition=ADULT, severity="high"):  # noqa: ANN001, ANN201
    rule = (
        c["manager"]
        .post(
            f"{API}/rules",
            json={
                "key": key,
                "name": f"Rule {key}",
                "category": "eligibility",
                "effective_from": "2026-01-01",
                "definition": {"condition": condition, "severity": severity},
                "source_reference": "Synthetic SYN-1",
                "change_summary": "Initial",
            },
        )
        .json()
    )
    vid = rule["versions"][0]["id"]
    assert c["manager"].post(f"{API}/rules/{rule['id']}/versions/{vid}/submit").status_code == 200
    assert (
        c["approver"].post(f"{API}/rules/{rule['id']}/versions/{vid}/approve", json={"note": "ok ok"}).status_code == 200
    )
    return rule


@pytest.fixture
def case(world):
    """A reviewer-owned application whose second document has a minor's date of birth: the adult rule fails."""
    publish_rule(world)
    owner = world["owner"]
    app = owner.post(f"{API}/applications", json={"title": "Synthetic review case", "application_type": "kyc"}).json()
    for name, dob in (("adult.pdf", "03 March 1990"), ("minor.pdf", "01 January 2015")):
        pdf = factories.labelled_pdf([["Full name: Test Person Alpha", f"Date of birth: {dob}"]])
        assert (
            owner.post(
                f"{API}/applications/{app['id']}/documents", files={"file": (name, pdf, "application/pdf")}
            ).status_code
            == 201
        )
    run = owner.post(f"{API}/applications/{app['id']}/validation-runs", json={"evaluation_date": ON}).json()
    assert run["summary"]["fail"] == 1
    items = owner.get(f"{API}/reviews").json()["items"]
    assert len(items) == 1
    return {"app": app, "run": run, "item": items[0]["item"]}


def act(client, item, action, **kw):  # noqa: ANN001, ANN201
    return client.post(
        f"{API}/reviews/{item['id']}/actions", json={"action": action, "expected_version": item["version"], **kw}
    )


def detail(client, item):  # noqa: ANN001, ANN201
    return client.get(f"{API}/reviews/{item['id']}").json()


# ------------------------------------------------------------------ queue and detail


def test_failed_result_opens_item_with_full_context(world, case):
    item = case["item"]
    assert (item["category"], item["outcome"], item["status"], item["severity"]) == ("failure", "fail", "open", "high")
    assert item["priority"] == 60
    d = detail(world["owner"], item)
    assert d["rule"]["source_reference"] == "Synthetic SYN-1" and d["rule"]["approved_by"] == "approver@example.org"
    assert "at least 18 years" in d["rule"]["summary"]["condition"]
    minor = next(f for f in d["fields"] if f["document_name"] == "minor.pdf" and f["field_key"] == "date_of_birth")
    assert (
        minor["raw_value"] == "01 January 2015" and minor["page_number"] == 1 and minor["bbox"] and minor["page_width"]
    )
    assert any(u["code"] == "condition_not_met" and "2015-01-01" in u["message"] for u in d["uncertainty"])
    assert [h["action"] for h in d["history"]] == ["opened"]
    assert d["permissions"] == {"can_act": True, "can_correct": True, "oversight": False, "can_decide": True}
    assert d["rule_runs"][0]["outcome"] == "fail"


def test_queue_filters_and_counts(world, case):
    owner = world["owner"]
    assert owner.get(f"{API}/reviews", params={"category": "missing"}).json()["total"] == 0
    assert owner.get(f"{API}/reviews", params={"category": "failure", "severity": "high"}).json()["total"] == 1
    assert owner.get(f"{API}/reviews", params={"q": "REVIEW CASE"}).json()["total"] == 1
    assert owner.get(f"{API}/reviews", params={"q": "100%_"}).json()["total"] == 0
    assert owner.get(f"{API}/reviews", params={"assignee": "me"}).json()["total"] == 0
    q = owner.get(f"{API}/reviews", params={"assignee": "unassigned"}).json()
    assert q["total"] == 1 and q["counts"]["category"] == {"failure": 1} and q["counts"]["status"] == {"open": 1}
    assert owner.get(f"{API}/reviews", params={"status": "bogus"}).status_code == 422


# ------------------------------------------------------------------ authorization


def test_cross_application_access_is_hidden(world, case):
    item, outsider = case["item"], world["outsider"]
    assert outsider.get(f"{API}/reviews").json()["total"] == 0
    assert outsider.get(f"{API}/reviews/{item['id']}").status_code == 404
    assert act(outsider, item, "commented", reason="peeking").status_code == 404
    r = outsider.post(
        f"{API}/reviews/{item['id']}/corrections",
        json={"expected_version": 1, "document_id": "x", "field_id": "y", "value": "1990-01-01", "reason": "nope nope"},
    )
    assert r.status_code == 404


def test_auditor_reads_but_cannot_act(world, case):
    item = case["item"]
    assert detail(world["auditor"], item)["permissions"]["can_act"] is False
    assert act(world["auditor"], item, "commented", reason="note").status_code == 403


def test_viewer_member_cannot_act(world, case):
    owner, item = world["owner"], case["item"]
    owner.post(
        f"{API}/applications/{case['app']['id']}/members", json={"email": "colleague@example.org", "role": "viewer"}
    )
    assert world["colleague"].get(f"{API}/reviews/{item['id']}").status_code == 200
    r = act(world["colleague"], item, "commented", reason="hello")
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"


def test_reviewer_cannot_publish_or_author_rules(world, case):
    rule = (
        world["manager"]
        .post(
            f"{API}/rules",
            json={
                "key": "second_rule",
                "name": "Second rule",
                "category": "x1",
                "effective_from": "2026-01-01",
                "definition": {"condition": ADULT, "severity": "low"},
                "source_reference": "SYN",
                "change_summary": "c",
            },
        )
        .json()
    )
    vid = rule["versions"][0]["id"]
    world["manager"].post(f"{API}/rules/{rule['id']}/versions/{vid}/submit")
    assert (
        world["owner"].post(f"{API}/rules/{rule['id']}/versions/{vid}/approve", json={"note": "mine"}).status_code
        == 403
    )
    assert world["owner"].post(f"{API}/rules", json={}).status_code == 403
    assert (
        world["owner"].post(f"{API}/rules/simulate", json={"proposals": [{"rule_id": rule["id"]}]}).status_code == 403
    )


# ------------------------------------------------------------------ actions, reasons and transitions


def test_assignment_and_reassignment(world, case):
    owner, item, ids = world["owner"], case["item"], world["ids"]
    owner.post(
        f"{API}/applications/{case['app']['id']}/members",
        json={"email": "colleague@example.org", "role": "contributor"},
    )
    names = {u["email"] for u in owner.get(f"{API}/reviews/{item['id']}/assignees").json()}
    assert names >= {"owner@example.org", "colleague@example.org", "manager@example.org"}
    assert "outsider@example.org" not in names and "auditor@example.org" not in names
    bad = act(owner, item, "assigned", assignee_id=ids["outsider"])
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_assignee"
    r = act(owner, item, "assigned", assignee_id=ids["colleague"]).json()
    assert r["item"]["assignee"]["email"] == "colleague@example.org" and r["item"]["version"] == 2
    # Taking it away from the colleague needs a reason.
    no_reason = act(owner, r["item"], "assigned", assignee_id=ids["owner"])
    assert no_reason.status_code == 422
    r = act(owner, r["item"], "assigned", assignee_id=ids["owner"], reason="Colleague is on leave").json()
    assert (
        r["action"]["data"]["from_assignee_id"] == ids["colleague"]
        and r["action"]["data"]["to_assignee_id"] == ids["owner"]
    )
    assert r["action"]["reason"] == "Colleague is on leave"
    assert owner.get(f"{API}/reviews", params={"assignee": "me"}).json()["total"] == 1


def test_sensitive_decisions_need_reasons(world, case):
    owner, item = world["owner"], case["item"]
    assert act(owner, item, "dismissed").status_code == 422
    assert act(owner, item, "dismissed", reason="too short").status_code == 422
    assert act(owner, item, "escalated", reason="").status_code == 422
    assert act(owner, item, "confirmed", reason="").status_code == 422
    r = act(owner, item, "dismissed", reason="Second document belongs to a dependant, not the applicant").json()
    assert r["item"]["status"] == "dismissed" and r["item"]["closed_by"]["email"] == "owner@example.org"
    assert r["action"]["from_status"] == "open" and r["action"]["to_status"] == "dismissed"
    assert act(owner, r["item"], "reopened").status_code == 422
    r = act(owner, r["item"], "reopened", reason="Dependant claim was not verified").json()
    assert r["item"]["status"] == "open" and r["item"]["closed_at"] is None


def test_escalation_requires_oversight_to_decide(world, case):
    owner, manager, item = world["owner"], world["manager"], case["item"]
    item = act(owner, item, "escalated", reason="Possible identity mismatch, need a manager").json()["item"]
    r = act(owner, item, "confirmed", reason="Confirmed it")
    assert r.status_code == 403 and r.json()["error"]["code"] == "oversight_required"
    assert detail(owner, item)["permissions"]["can_decide"] is False
    r = act(manager, item, "confirmed", reason="Applicant is a minor per synthetic doc")
    assert r.status_code == 200 and r.json()["item"]["status"] == "confirmed"


def test_document_request_and_resume(world, case):
    owner, item = world["owner"], case["item"]
    assert act(owner, item, "document_requested", document_description="ok").status_code == 422
    r = act(owner, item, "document_requested", document_description="Certified birth certificate").json()
    assert r["item"]["status"] == "awaiting_document"
    assert r["item"]["document_request"]["description"] == "Certified birth certificate"
    assert owner.get(f"{API}/reviews", params={"status": "awaiting_document"}).json()["total"] == 1
    r = act(owner, r["item"], "resumed").json()
    assert r["item"]["status"] == "open" and r["item"]["document_request"] is None
    assert act(owner, r["item"], "resumed").status_code == 409  # invalid transition


def test_critical_failure_dismissal_requires_oversight(world, case):
    owner = world["owner"]
    publish_rule(world, key="critical_rule", severity="critical")
    owner.post(f"{API}/applications/{case['app']['id']}/validation-runs", json={"evaluation_date": ON})
    crit = next(r["item"] for r in owner.get(f"{API}/reviews").json()["items"] if r["item"]["severity"] == "critical")
    assert crit["priority"] == 70
    r = act(owner, crit, "dismissed", reason="I think this does not apply here")
    assert r.status_code == 403 and r.json()["error"]["code"] == "oversight_required"
    assert act(world["manager"], crit, "dismissed", reason="Reviewed with the applicant's guardian").status_code == 200


def test_system_actions_cannot_be_submitted(world, case):
    r = act(world["owner"], case["item"], "revalidated")
    assert r.status_code == 422


# ------------------------------------------------------------------ concurrency and idempotency


def test_conflicting_decisions_are_refused(world, case):
    owner, manager, item = world["owner"], world["manager"], case["item"]
    first = act(owner, item, "confirmed", reason="Minor confirmed")  # both clients loaded version 1
    second = act(manager, item, "dismissed", reason="Not a real issue at all")
    assert first.status_code == 200
    assert second.status_code == 409 and second.json()["error"]["code"] == "stale_item"
    assert second.json()["error"]["details"]["status"] == "confirmed"
    assert detail(owner, item)["item"]["status"] == "confirmed"


def test_concurrent_writers_race_at_the_database(world, case, session_factory):
    """Two sessions read version 1 and both write: the optimistic lock refuses the second UPDATE."""
    from sqlalchemy.orm.exc import StaleDataError

    with session_factory() as s1, session_factory() as s2:
        a, b = s1.get(ReviewItem, case["item"]["id"]), s2.get(ReviewItem, case["item"]["id"])
        a.status = "escalated"
        s1.commit()
        b.status = "dismissed"
        with pytest.raises(StaleDataError):
            s2.commit()


def test_duplicate_requests_are_idempotent(world, case, session_factory):
    owner, item = world["owner"], case["item"]
    body = {"reason": "Looks like a dependant document", "request_id": "req-12345678"}
    one = act(owner, item, "commented", **body)
    two = act(owner, item, "commented", **body)  # retried with the stale version: still a replay, not a conflict
    assert one.status_code == two.status_code == 200
    assert two.json()["replayed"] is True and two.json()["action"]["id"] == one.json()["action"]["id"]
    with session_factory() as s:
        assert s.execute(select(ReviewAction).where(ReviewAction.action == "commented")).scalars().all().__len__() == 1
    reused = act(owner, one.json()["item"], "escalated", reason="different thing", request_id="req-12345678")
    assert reused.status_code == 409 and reused.json()["error"]["code"] == "request_id_reused"


# ------------------------------------------------------------------ corrections and revalidation


def _minor_field(session_factory, app_id: str) -> ExtractedField:  # noqa: ARG001
    with session_factory() as s:
        return s.execute(
            select(ExtractedField).where(
                ExtractedField.field_key == "date_of_birth", ExtractedField.raw_value == "01 January 2015"
            )
        ).scalar_one()


def test_correction_revalidates_and_links_runs(world, case, session_factory):
    owner, item = world["owner"], case["item"]
    field = _minor_field(session_factory, case["app"]["id"])
    assert (
        owner.post(
            f"{API}/reviews/{item['id']}/corrections",
            json={
                "expected_version": 1,
                "document_id": field.document_id,
                "field_id": field.id,
                "value": "1990-03-03",
                "reason": "",
            },
        ).status_code
        == 422
    )
    r = owner.post(
        f"{API}/reviews/{item['id']}/corrections",
        json={
            "expected_version": 1,
            "document_id": field.document_id,
            "field_id": field.id,
            "value": "1990-03-03",
            "reason": "OCR misread; synthetic source shows 1990",
            "request_id": "corr-0001",
        },
    )
    assert r.status_code == 200, r.text
    out = r.json()
    a = out["action"]
    assert (
        a["action"] == "field_corrected" and a["data"]["before"] == "2015-01-01" and a["data"]["after"] == "1990-03-03"
    )
    assert a["data"]["original_extraction"]["raw_value"] == "01 January 2015"
    assert a["data"]["affected_rules"] == ["adult_applicant"]
    rv = out["revalidation"]
    assert rv["performed"] and rv["previous_run_id"] == case["run"]["id"] and rv["summary"]["pass"] == 1
    # The item was resolved by the new run; nothing was deleted.
    assert out["item"]["status"] == "resolved" and out["item"]["current_run_id"] == rv["run_id"]
    assert out["item"]["origin_result_id"] != out["item"]["current_result_id"]
    d = detail(owner, out["item"])
    assert [h["action"] for h in d["history"]] == ["opened", "field_corrected", "revalidated"]
    assert d["history"][2]["data"]["before"]["outcome"] == "fail" and d["history"][2]["to_status"] == "resolved"
    assert [x["outcome"] for x in d["rule_runs"]] == ["pass", "fail"]
    # The original extraction and the original result are untouched.
    with session_factory() as s:
        assert s.get(ExtractedField, field.id).raw_value == "01 January 2015"
        assert s.get(ExtractedField, field.id).normalized_value == "2015-01-01"
        assert s.get(RuleResult, out["item"]["origin_result_id"]).outcome == "fail"
        new_run = s.get(ValidationRun, rv["run_id"])
        assert new_run.trigger == "correction" and new_run.trigger_data["review_item_id"] == item["id"]
    old = owner.get(f"{API}/applications/{case['app']['id']}/validation-runs/{case['run']['id']}").json()
    assert old["next_run_ids"] == [rv["run_id"]] and old["summary"]["fail"] == 1
    # Retrying the same correction request does not correct twice.
    again = owner.post(
        f"{API}/reviews/{item['id']}/corrections",
        json={
            "expected_version": 1,
            "document_id": field.document_id,
            "field_id": field.id,
            "value": "1990-03-03",
            "reason": "OCR misread; synthetic source shows 1990",
            "request_id": "corr-0001",
        },
    ).json()
    assert again["replayed"] is True


def test_correction_of_unrelated_field_does_not_revalidate(world, case, session_factory):
    owner, item = world["owner"], case["item"]
    with session_factory() as s:
        name = s.execute(select(ExtractedField).where(ExtractedField.field_key == "full_name")).scalars().first()
    r = owner.post(
        f"{API}/reviews/{item['id']}/corrections",
        json={
            "expected_version": 1,
            "document_id": name.document_id,
            "field_id": name.id,
            "value": "Test Person Beta",
            "reason": "Typo in the synthetic name",
        },
    ).json()
    assert r["revalidation"]["performed"] is False and "No rule in force" in r["revalidation"]["reason"]
    assert r["item"]["status"] == "open" and r["item"]["version"] == 2


def test_stale_version_blocks_correction(world, case, session_factory):
    owner, item = world["owner"], case["item"]
    act(owner, item, "commented", reason="first")
    field = _minor_field(session_factory, case["app"]["id"])
    r = owner.post(
        f"{API}/reviews/{item['id']}/corrections",
        json={
            "expected_version": 1,
            "document_id": field.document_id,
            "field_id": field.id,
            "value": "1990-03-03",
            "reason": "based on an old view",
        },
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "stale_item"


def test_unchanged_revalidation_keeps_decision_and_new_evidence_reopens(world, case):
    owner, item, app_id = world["owner"], case["item"], case["app"]["id"]
    act(owner, item, "dismissed", reason="Second document belongs to a dependant")
    owner.post(f"{API}/applications/{app_id}/validation-runs", json={"evaluation_date": ON})
    q = owner.get(f"{API}/reviews", params={"status": "all"}).json()
    assert q["total"] == 1  # the decision stands on identical evidence; no duplicate item
    hist = detail(owner, item)["history"]
    assert hist[-1]["action"] == "revalidated" and hist[-1]["data"]["decision_stands"] is True
    # New evidence (a third document) changes the trace: a new item is opened and linked to the dismissed one.
    pdf = factories.labelled_pdf([["Full name: Test Person Alpha", "Date of birth: 05 May 2012"]])
    owner.post(f"{API}/applications/{app_id}/documents", files={"file": ("other.pdf", pdf, "application/pdf")})
    owner.post(f"{API}/applications/{app_id}/validation-runs", json={"evaluation_date": ON})
    active = owner.get(f"{API}/reviews").json()["items"]
    assert len(active) == 1 and active[0]["item"]["previous_item_id"] == item["id"]
    assert detail(owner, active[0]["item"])["previous_items"][0]["status"] == "dismissed"


def test_archived_application_blocks_actions(world, case):
    owner = world["owner"]
    owner.post(f"{API}/applications/{case['app']['id']}/transitions", json={"action": "archive", "reason": "done here"})
    r = act(owner, case["item"], "commented", reason="late")
    assert r.status_code == 409 and r.json()["error"]["code"] == "application_archived"


# ------------------------------------------------------------------ immutable history and audit


def test_history_is_append_only_and_audited(world, case, session_factory):
    owner, item = world["owner"], case["item"]
    act(owner, item, "commented", reason="Checked both documents")
    with session_factory() as s:
        entry = s.execute(select(ReviewAction).where(ReviewAction.action == "commented")).scalar_one()
        entry.reason = "rewritten"
        with pytest.raises(ImmutableReviewActionError):
            s.flush()
        s.rollback()
        with pytest.raises(Exception, match="append-only"):
            s.execute(text("UPDATE review_actions SET reason = 'x'"))
        s.rollback()
        with pytest.raises(Exception, match="append-only"):
            s.execute(text("DELETE FROM review_actions"))
        s.rollback()
        it = s.get(ReviewItem, item["id"])
        s.delete(it)
        with pytest.raises(ImmutableReviewActionError):
            s.flush()
        s.rollback()
        actions = [a for (a,) in s.execute(select(AuditEvent.action).where(AuditEvent.action.like("review.%")))]
        assert actions == ["review.commented"]
    assert world["auditor"].get(f"{API}/audit/verify").json()["valid"] is True
