"""Rule lifecycle, authorization, immutability, effective dating, validation runs and simulation isolation."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import func, select

from app.core.roles import Role
from app.models import AuditEvent, Rule, RuleResult, RuleTestCase, RuleVersion, ValidationRun
from app.models.rules import ImmutableRuleVersionError, ImmutableRunError
from app.services import rule_service
from tests import factories

API = "/api/v1"

ADULT = {"field": "extracted.date_of_birth", "op": "age_years_at_least", "value": 18}
CASE_ADULT = {
    "synthetic": True,
    "evaluation_date": "2026-10-23",
    "documents": [{"name": "Synthetic ID", "fields": {"date_of_birth": {"value": "1990-03-03"}}}],
}
CASE_MINOR = {
    **CASE_ADULT,
    "documents": [{"name": "Synthetic ID", "fields": {"date_of_birth": {"value": "2015-01-01"}}}],
}


@pytest.fixture
def people(make_user, login):
    make_user(Role.COMPLIANCE_MANAGER, email="author@example.org")
    make_user(Role.SECOND_APPROVER, email="approver@example.org")
    make_user(Role.REVIEWER, email="reviewer@example.org")
    make_user(Role.AUDITOR, email="auditor@example.org")
    return {n: login(f"{n}@example.org") for n in ("author", "approver", "reviewer", "auditor")}


def create(c, key="adult_applicant", condition=ADULT, effective_from="2026-01-01", **kw):  # noqa: ANN001, ANN201
    body = {
        "key": key,
        "name": "Applicant is an adult",
        "category": "eligibility",
        "definition": {
            "condition": condition,
            "severity": "high",
            "fail_message": "Applicant under 18 (synthetic rule)",
        },
        "effective_from": effective_from,
        "source_reference": "Synthetic internal policy SYN-1 §2",
        "change_summary": "Initial version",
        **kw,
    }
    r = c.post(f"{API}/rules", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def draft(rule: dict) -> dict:
    return next(v for v in rule["versions"] if v["status"] == "draft")


def publish(people, rule: dict, version_id: str | None = None) -> dict:  # noqa: ANN001
    vid = version_id or draft(rule)["id"]
    base = f"{API}/rules/{rule['id']}/versions/{vid}"
    r = people["author"].post(f"{base}/submit")
    assert r.status_code == 200, r.text
    r = people["approver"].post(f"{base}/approve", json={"note": "Reviewed against SYN-1"})
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ lifecycle and authorization


def test_full_lifecycle_with_four_eyes(people, session_factory):
    rule = create(people["author"])
    v1 = draft(rule)
    assert v1["version_number"] == 1 and v1["summary"]["condition"].startswith("Date of birth")
    base = f"{API}/rules/{rule['id']}/versions/{v1['id']}"
    assert people["author"].post(f"{base}/approve", json={"note": "self"}).status_code == 403
    assert people["author"].post(f"{base}/submit").status_code == 200
    r = people["author"].post(f"{base}/approve", json={"note": "approving my own"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    published = people["approver"].post(f"{base}/approve", json={"note": "Reviewed"}).json()
    v = published["versions"][0]
    assert v["status"] == "published" and v["reviewed_by"]["email"] == "approver@example.org"
    assert v["in_force_today"] is True and published["owner"]["email"] == "author@example.org"
    assert "not a legal or regulatory determination" in published["disclaimer"]
    retired = people["approver"].post(f"{base}/retire", json={"reason": "Replaced by policy SYN-2"}).json()
    assert retired["versions"][0]["status"] == "retired" and retired["versions"][0]["in_force_today"] is False
    with session_factory() as s:
        actions = [a for (a,) in s.execute(select(AuditEvent.action).where(AuditEvent.entity_id == rule["id"]))]
    assert actions == ["rule.created", "rule.submitted", "rule.published", "rule.retired"]


def test_reject_is_terminal_and_four_eyes(people):
    rule = create(people["author"])
    base = f"{API}/rules/{rule['id']}/versions/{draft(rule)['id']}"
    people["author"].post(f"{base}/submit")
    assert people["author"].post(f"{base}/reject", json={"note": "nope"}).status_code == 403
    r = people["approver"].post(f"{base}/reject", json={"note": "Source clause is wrong"})
    assert r.json()["versions"][0]["status"] == "rejected"
    assert people["approver"].post(f"{base}/approve", json={"note": "late"}).status_code == 409


@pytest.mark.parametrize("who,create_status,publish_status", [("reviewer", 403, 403), ("auditor", 403, 403)])
def test_role_restrictions(people, who, create_status, publish_status):
    assert people[who].get(f"{API}/rules").status_code == 200  # rules:read
    body = {
        "key": "x_rule",
        "name": "X rule",
        "category": "test",
        "effective_from": "2026-01-01",
        "definition": {"condition": ADULT, "severity": "low"},
    }
    assert people[who].post(f"{API}/rules", json=body).status_code == create_status
    rule = create(people["author"])
    base = f"{API}/rules/{rule['id']}/versions/{draft(rule)['id']}"
    people["author"].post(f"{base}/submit")
    assert people[who].post(f"{base}/approve", json={"note": "x" * 5}).status_code == publish_status
    assert people[who].post(f"{API}/rules/simulate", json={"proposals": [{"rule_id": rule["id"]}]}).status_code == 403


def test_unauthenticated(client):
    assert client.get(f"{API}/rules").status_code == 401


def test_submission_requirements(people):
    rule = create(people["author"], source_reference="", change_summary="")
    base = f"{API}/rules/{rule['id']}/versions/{draft(rule)['id']}"
    r = people["author"].post(f"{base}/submit")
    assert r.status_code == 422 and "source" in r.json()["error"]["message"]
    people["author"].patch(base, json={"source_reference": "SYN-1 §2"})
    assert "Describe what this version changes" in people["author"].post(f"{base}/submit").json()["error"]["message"]


# ------------------------------------------------------------------ immutability and versions


def test_submitted_versions_are_immutable(people, session_factory):
    rule = create(people["author"])
    vid = draft(rule)["id"]
    base = f"{API}/rules/{rule['id']}/versions/{vid}"
    assert people["author"].patch(base, json={"change_summary": "edited while draft"}).status_code == 200
    publish(people, rule)
    r = people["author"].patch(base, json={"definition": {"condition": ADULT, "severity": "low"}})
    assert r.status_code == 409 and r.json()["error"]["code"] == "immutable"
    with session_factory() as s:
        v = s.get(RuleVersion, vid)
        v.definition = {"tampered": True}
        with pytest.raises(ImmutableRuleVersionError):
            s.flush()
        s.rollback()
        v = s.get(RuleVersion, vid)
        s.delete(v)
        with pytest.raises(ImmutableRuleVersionError):
            s.flush()


def test_new_version_history_and_comparison(people):
    rule = create(people["author"])
    publish(people, rule)
    r = people["author"].post(f"{API}/rules/{rule['id']}/versions", json={})
    assert r.status_code == 201
    v2 = draft(r.json())
    assert v2["version_number"] == 2
    assert (
        people["author"].post(f"{API}/rules/{rule['id']}/versions", json={}).json()["error"]["code"] == "draft_exists"
    )
    changed = {"condition": {**ADULT, "value": 21}, "severity": "critical"}
    people["author"].patch(
        f"{API}/rules/{rule['id']}/versions/{v2['id']}", json={"definition": changed, "change_summary": "Raise to 21"}
    )
    v1 = next(v for v in r.json()["versions"] if v["version_number"] == 1)
    diff = people["auditor"].get(f"{API}/rules/{rule['id']}/compare", params={"from": v1["id"], "to": v2["id"]}).json()
    paths = {c["path"]: (c["before"], c["after"]) for c in diff["changes"]}
    assert paths["definition.condition.value"] == (18, 21) and paths["definition.severity"] == ("high", "critical")
    assert "at least 21 years" in diff["to"]["summary"]["condition"]


def test_invalid_definitions_rejected_with_details(people):
    r = people["author"].post(
        f"{API}/rules",
        json={
            "key": "bad_rule",
            "name": "Bad rule",
            "category": "test",
            "effective_from": "2026-01-01",
            "definition": {"condition": {"field": "extracted.full_name", "op": "gt", "value": "a"}, "severity": "high"},
        },
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_rule"
    assert "not allowed for text" in r.json()["error"]["details"][0]["msg"]
    check = (
        people["reviewer"]
        .post(f"{API}/rules/validate", json={"definition": {"condition": ADULT, "severity": "x"}})
        .json()
    )
    assert check["valid"] is False and check["errors"]
    ok = (
        people["reviewer"]
        .post(f"{API}/rules/validate", json={"definition": {"condition": ADULT, "severity": "low"}})
        .json()
    )
    assert ok["valid"] and "18 years" in ok["summary"]["condition"]


def test_effective_window_validation(people):
    r = people["author"].post(
        f"{API}/rules",
        json={
            "key": "window_rule",
            "name": "Window rule",
            "category": "test",
            "effective_from": "2026-05-01",
            "effective_to": "2026-05-01",
            "definition": {"condition": ADULT, "severity": "low"},
        },
    )
    assert r.status_code == 422


# ------------------------------------------------------------------ effective dates


def test_effective_date_selection_boundaries(people, session_factory):
    rule = create(people["author"], effective_from="2026-01-01")
    publish(people, rule)
    r = people["author"].post(f"{API}/rules/{rule['id']}/versions", json={}).json()
    v2 = draft(r)
    people["author"].patch(
        f"{API}/rules/{rule['id']}/versions/{v2['id']}",
        json={"effective_from": "2026-07-01", "effective_to": "2027-01-01", "change_summary": "Half-year variant"},
    )
    publish(people, r, v2["id"])
    with session_factory() as s:
        versions = s.get(Rule, rule["id"]).versions
        pick = lambda d: (v := rule_service.effective_on(versions, d)) and v.version_number  # noqa: E731
        assert pick(date(2025, 12, 31)) is None  # before any version
        assert pick(date(2026, 1, 1)) == 1  # effective_from is inclusive
        assert pick(date(2026, 6, 30)) == 1
        assert pick(date(2026, 7, 1)) == 2  # newer version supersedes from its start
        assert pick(date(2026, 12, 31)) == 2
        assert pick(date(2027, 1, 1)) is None  # effective_to is exclusive; superseded v1 does not revive


def test_same_effective_date_clash(people):
    rule = create(people["author"])
    publish(people, rule)
    r = people["author"].post(f"{API}/rules/{rule['id']}/versions", json={}).json()
    v2 = draft(r)
    people["author"].patch(f"{API}/rules/{rule['id']}/versions/{v2['id']}", json={"change_summary": "same date"})
    people["author"].post(f"{API}/rules/{rule['id']}/versions/{v2['id']}/submit")
    clash = people["approver"].post(f"{API}/rules/{rule['id']}/versions/{v2['id']}/approve", json={"note": "ok ok"})
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "effective_date_clash"


# ------------------------------------------------------------------ synthetic test cases


def test_test_cases_gate_submission(people):
    rule = create(people["author"])
    base = f"{API}/rules/{rule['id']}"
    assert (
        people["author"]
        .post(f"{base}/test-cases", json={"name": "Adult passes", "case": CASE_ADULT, "expected_outcome": "pass"})
        .status_code
        == 201
    )
    wrong = (
        people["author"]
        .post(
            f"{base}/test-cases",
            json={"name": "Minor (wrong expectation)", "case": CASE_MINOR, "expected_outcome": "pass"},
        )
        .json()
    )
    vid = draft(rule)["id"]
    run = people["auditor"].post(f"{base}/versions/{vid}/test").json()
    assert (run["total"], run["passed"], run["failed"]) == (2, 1, 1)
    r = people["author"].post(f"{base}/versions/{vid}/submit")
    assert r.status_code == 409 and r.json()["error"]["code"] == "tests_failing"
    assert r.json()["error"]["details"][0] == {
        "name": "Minor (wrong expectation)",
        "expected": "pass",
        "actual": "fail",
    }
    people["author"].delete(f"{base}/test-cases/{wrong['id']}")
    people["author"].post(
        f"{base}/test-cases", json={"name": "Minor fails", "case": CASE_MINOR, "expected_outcome": "fail"}
    )
    submitted = people["author"].post(f"{base}/versions/{vid}/submit").json()
    assert submitted["versions"][0]["test_summary"] == {"total": 2, "passed": 2, "failed": 0}
    preview = (
        people["author"]
        .post(f"{base}/test-definition", json={"definition": {"condition": {**ADULT, "value": 40}, "severity": "high"}})
        .json()
    )
    assert preview["failed"] == 1  # unsaved edit previewed without touching the submitted version


@pytest.mark.parametrize(
    "case,msg",
    [
        ({**CASE_ADULT, "synthetic": False}, "synthetic"),
        ({**CASE_ADULT, "documents": [{"name": "X", "fields": {"salary": {"value": "1"}}}]}, "unknown field"),
        ({k: v for k, v in CASE_ADULT.items() if k != "synthetic"}, "synthetic"),
    ],
)
def test_test_cases_must_be_synthetic_and_valid(people, case, msg):
    rule = create(people["author"])
    r = people["author"].post(
        f"{API}/rules/{rule['id']}/test-cases", json={"name": "Bad case", "case": case, "expected_outcome": "pass"}
    )
    assert r.status_code == 422 and msg in str(r.json()["error"])


# ------------------------------------------------------------------ validation runs: traceability and reproducibility


@pytest.fixture
def app_with_docs(people):
    c = people["author"]
    app_id = c.post(f"{API}/applications", json={"title": "Synthetic rules case", "application_type": "kyc"}).json()[
        "id"
    ]
    pdf = factories.labelled_pdf([["Full name: Test Person Alpha", "Date of birth: 03 March 1990"]])
    c.post(f"{API}/applications/{app_id}/documents", files={"file": ("id.pdf", pdf, "application/pdf")})
    return app_id


def test_validation_run_traceable_and_reproducible(people, app_with_docs, session_factory):
    rule = create(people["author"])
    publish(people, rule)
    c = people["author"]
    first = c.post(f"{API}/applications/{app_with_docs}/validation-runs", json={"evaluation_date": "2026-10-23"})
    assert first.status_code == 201, first.text
    run = first.json()
    assert run["summary"]["pass"] == 1 and "not a legal" in run["disclaimer"]
    used = run["rule_versions"][0]
    assert used["rule_key"] == "adult_applicant" and used["approved_by"] == "approver@example.org"
    assert (
        used["definition"]["condition"] == {**ADULT, "quantifier": "all"}
        and used["source_reference"] == "Synthetic internal policy SYN-1 §2"
    )
    obs = run["results"][0]["trace"][0]["observations"][0]
    docs = c.get(f"{API}/applications/{app_with_docs}/documents").json()
    assert obs["document_id"] == docs[0]["id"] and obs["page_number"] == 1 and obs["bbox"]
    assert obs["value"] == "1990-03-03" and obs["raw_value"] == "03 March 1990"

    second = c.post(
        f"{API}/applications/{app_with_docs}/validation-runs", json={"evaluation_date": "2026-10-23"}
    ).json()
    assert second["input_fingerprint"] == run["input_fingerprint"]
    assert [(r["outcome"], r["trace"]) for r in second["results"]] == [
        (r["outcome"], r["trace"]) for r in run["results"]
    ]
    repro = people["auditor"].get(f"{API}/applications/{app_with_docs}/validation-runs/{run['id']}/reproduction").json()
    assert repro == {**repro, "identical": True, "snapshot_intact": True, "differences": []}

    # Publishing a stricter version later does not change the stored run.
    r = c.post(f"{API}/rules/{rule['id']}/versions", json={}).json()
    v2 = draft(r)
    c.patch(
        f"{API}/rules/{rule['id']}/versions/{v2['id']}",
        json={
            "definition": {"condition": {**ADULT, "value": 50}, "severity": "high"},
            "effective_from": "2026-10-01",
            "change_summary": "Stricter",
        },
    )
    publish(people, r, v2["id"])
    third = c.post(f"{API}/applications/{app_with_docs}/validation-runs", json={"evaluation_date": "2026-10-23"}).json()
    assert third["summary"]["fail"] == 1 and third["rule_versions"][0]["version_number"] == 2
    old = c.get(f"{API}/applications/{app_with_docs}/validation-runs/{run['id']}").json()
    assert old["summary"]["pass"] == 1 and old["rule_versions"][0]["version_number"] == 1
    assert (
        people["auditor"]
        .get(f"{API}/applications/{app_with_docs}/validation-runs/{run['id']}/reproduction")
        .json()["identical"]
    )

    with session_factory() as s:
        stored = s.get(ValidationRun, run["id"])
        stored.summary = {"pass": 99}
        with pytest.raises(ImmutableRunError):
            s.flush()


def test_validation_requires_rules_in_force_and_permissions(people, app_with_docs, make_user, login):
    url = f"{API}/applications/{app_with_docs}/validation-runs"
    r = people["author"].post(url, json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_rules_in_force"
    rule = create(people["author"])
    publish(people, rule)
    assert people["auditor"].post(url, json={}).status_code == 403  # read-only role
    assert people["reviewer"].post(url, json={}).status_code == 404  # not their application
    assert (
        people["author"].post(url, json={"evaluation_date": "2025-06-01"}).json()["error"]["code"]
        == "no_rules_in_force"
    )


# ------------------------------------------------------------------ simulation isolation


def _counts(session_factory) -> dict:  # noqa: ANN001
    with session_factory() as s:
        out = {
            m.__name__: s.execute(select(func.count()).select_from(m)).scalar_one()
            for m in (Rule, RuleVersion, RuleTestCase, ValidationRun, RuleResult)
        }
        out["statuses"] = sorted((v.id, v.status, v.content_hash) for v in s.execute(select(RuleVersion)).scalars())
        return out


def test_simulation_is_isolated(people, app_with_docs, session_factory):
    rule = create(people["author"])
    publish(people, rule)
    people["author"].post(f"{API}/applications/{app_with_docs}/validation-runs", json={"evaluation_date": "2026-10-23"})
    before = _counts(session_factory)
    stricter = {"condition": {**ADULT, "value": 50}, "severity": "critical"}
    r = people["approver"].post(
        f"{API}/rules/simulate",
        json={"proposals": [{"rule_id": rule["id"], "definition": stricter}], "evaluation_date": "2026-10-23"},
    )
    assert r.status_code == 200, r.text
    sim = r.json()
    assert sim["side_effects"].startswith("None")
    row = next(a for a in sim["applications"] if a["application_id"] == app_with_docs)["rules"][0]
    assert row["before"]["outcome"] == "pass" and row["after"]["outcome"] == "fail" and row["changed"]
    assert row["after"]["version"] == "unsaved edit"
    assert _counts(session_factory) == before  # nothing created or modified
    with session_factory() as s:
        audit = s.execute(select(AuditEvent).where(AuditEvent.action == "rule.simulated")).scalar_one()
        assert audit.data["rule_ids"] == [rule["id"]]
    # The rule in force is unchanged: a real run still passes.
    real = (
        people["author"]
        .post(f"{API}/applications/{app_with_docs}/validation-runs", json={"evaluation_date": "2026-10-23"})
        .json()
    )
    assert real["summary"]["pass"] == 1


def test_simulating_a_draft_version_and_invalid_proposals(people, app_with_docs):
    rule = create(people["author"])
    publish(people, rule)
    r = people["author"].post(f"{API}/rules/{rule['id']}/versions", json={}).json()
    v2 = draft(r)
    sim = (
        people["author"]
        .post(
            f"{API}/rules/simulate",
            json={
                "proposals": [{"rule_id": rule["id"], "version_id": v2["id"]}],
                "application_ids": [app_with_docs],
                "evaluation_date": "2026-10-23",
            },
        )
        .json()
    )
    assert sim["applications"][0]["rules"][0]["after"]["version"] == "v2 (draft)"
    bad = people["author"].post(
        f"{API}/rules/simulate",
        json={
            "proposals": [
                {"rule_id": rule["id"], "definition": {"condition": {"field": "x.y", "op": "eq"}, "severity": "low"}}
            ]
        },
    )
    assert bad.status_code == 422
    assert (
        people["reviewer"]
        .post(f"{API}/rules/simulate", json={"proposals": [{"rule_id": rule["id"], "version_id": v2["id"]}]})
        .status_code
        == 403
    )
