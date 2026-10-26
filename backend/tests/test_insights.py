"""Governance and insights (Phase 10): aggregation correctness without double counting, scoping, date windows,
pagination, audit filters, export authorization and audit immutability, and labelled synthetic demo data."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from app.core.roles import Role
from app.models import Application, AuditEvent, ExtractedField
from app.models.audit import AuditImmutableError
from app.services import demo_seed
from tests import factories

API = "/api/v1"
ON = "2026-10-23"
ADULT = {"field": "extracted.date_of_birth", "op": "age_years_at_least", "value": 18}
TODAY = datetime.now(UTC).date()


@pytest.fixture
def world(make_user, login):
    make_user(Role.ADMIN, email="author@example.org")
    make_user(Role.COMPLIANCE_MANAGER, email="manager@example.org")
    make_user(Role.SECOND_APPROVER, email="approver@example.org")
    make_user(Role.REVIEWER, email="owner@example.org")
    make_user(Role.REVIEWER, email="outsider@example.org")
    make_user(Role.AUDITOR, email="auditor@example.org")
    c = {n: login(f"{n}@example.org") for n in ("author", "manager", "approver", "owner", "outsider", "auditor")}
    c["ids"] = {n: c[n].get(f"{API}/auth/me").json()["id"] for n in ("owner", "manager")}
    rule = c["manager"].post(f"{API}/rules", json={
        "key": "adult_applicant", "name": "Applicant is an adult", "category": "eligibility",
        "effective_from": "2026-01-01", "definition": {"condition": ADULT, "severity": "high"},
        "source_reference": "Synthetic SYN-1", "change_summary": "Initial",
    }).json()
    vid = rule["versions"][0]["id"]
    assert c["manager"].post(f"{API}/rules/{rule['id']}/versions/{vid}/submit").status_code == 200
    approve = c["approver"].post(f"{API}/rules/{rule['id']}/versions/{vid}/approve", json={"note": "ok ok"})
    assert approve.status_code == 200
    c["rule"] = rule
    return c


def make_app(client, title: str, dobs: list[str], app_type: str = "kyc") -> dict:  # noqa: ANN001
    app = client.post(f"{API}/applications", json={"title": title, "application_type": app_type}).json()
    for i, dob in enumerate(dobs):
        pdf = factories.labelled_pdf([["Full name: Test Person Alpha", f"Date of birth: {dob}"]])
        files = {"file": (f"d{i}.pdf", pdf, "application/pdf")}
        r = client.post(f"{API}/applications/{app['id']}/documents", files=files)
        assert r.status_code == 201, r.text
    return app


def validate(client, app_id: str) -> dict:  # noqa: ANN001
    r = client.post(f"{API}/applications/{app_id}/validation-runs", json={"evaluation_date": ON})
    assert r.status_code == 201, r.text
    return r.json()


def overview(client, **params) -> dict:  # noqa: ANN001, ANN003
    r = client.get(f"{API}/insights/overview", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def act(client, item: dict, action: str, **kw) -> dict:  # noqa: ANN001, ANN003
    r = client.post(f"{API}/reviews/{item['id']}/actions",
                    json={"action": action, "expected_version": item["version"], **kw})
    assert r.status_code == 200, r.text
    return r.json()["item"]


def export(client, **body):  # noqa: ANN001, ANN003, ANN201
    return client.post(f"{API}/exports", json=body)


# ------------------------------------------------------------------ aggregation correctness


def test_repeated_runs_are_not_double_counted(world):
    owner = world["owner"]
    app = make_app(owner, "Minor case", ["03 March 1990", "01 January 2015"])
    for _ in range(3):
        validate(owner, app["id"])
    o = overview(owner)
    f = o["current"]["findings"]
    assert f["by_outcome"] == {"fail": 1} and f["engine_failures"] == 1 and f["applications_with_run"] == 1
    assert f["by_outcome_severity"] == [{"outcome": "fail", "severity": "high", "count": 1}]
    assert f["rates"] == {"denominator": 1, "uncertainty": 0.0, "insufficient": 0.0}
    v = o["window"]["validation"]
    assert v["runs"] == 3 and v["by_trigger"] == {"manual": 3}
    assert v["cases"] == {"applications": 1, "by_outcome": {"fail": 1}}
    assert sum(d["manual"] for d in v["by_day"]) == 3
    # One review item, however many runs.
    assert o["current"]["review"]["backlog"] == 1 and o["current"]["review"]["backlog_by_category"] == {"failure": 1}

    usage = owner.get(f"{API}/insights/rules").json()["version_usage"]
    assert len(usage) == 1
    assert (usage[0]["rule_key"], usage[0]["runs"], usage[0]["applications"], usage[0]["latest_outcomes"]) == (
        "adult_applicant", 3, 1, {"fail": 1})


def test_current_state_follows_latest_run_and_history_keeps_both(world, session_factory):
    owner = world["owner"]
    app = make_app(owner, "Corrected case", ["03 March 1990", "01 January 2015"])
    validate(owner, app["id"])
    item = owner.get(f"{API}/reviews").json()["items"][0]["item"]
    with session_factory() as s:
        field = s.execute(select(ExtractedField).where(ExtractedField.raw_value == "01 January 2015")).scalar_one()
    r = owner.post(f"{API}/reviews/{item['id']}/corrections", json={
        "expected_version": item["version"], "document_id": field.document_id, "field_id": field.id,
        "value": "1990-03-03", "reason": "Synthetic source shows 1990",
    })
    assert r.status_code == 200 and r.json()["revalidation"]["performed"] is True
    o = overview(owner)
    assert o["current"]["findings"]["by_outcome"] == {"pass": 1}
    assert o["window"]["validation"]["by_trigger"] == {"manual": 1, "correction": 1}
    assert o["window"]["validation"]["cases"]["by_outcome"] == {"pass": 1}
    assert o["current"]["review"]["by_status"] == {"resolved": 1} and o["current"]["review"]["backlog"] == 0
    ext = o["current"]["extraction"]
    assert ext["correction_rate"]["corrected"] == 1 and ext["correction_rate"]["eligible"] == 4
    assert ext["correction_rate"]["rate"] == 0.25 and o["window"]["extraction"]["corrections"] == 1


def test_extraction_and_document_counts(world):
    owner = world["owner"]
    make_app(owner, "Two documents", ["03 March 1990", "31/02/2026"])
    o = overview(owner)
    assert o["current"]["applications"]["total"] == 1 and o["current"]["documents"]["total"] == 2
    ext = o["current"]["extraction"]
    assert ext["documents_with_current_run"] == 2
    # Two documents x eight configured fields: full name and one date of birth found, one invalid date.
    assert sum(ext["fields_by_status"].values()) == 16
    assert ext["fields_by_status"]["found"] == 3 and ext["fields_by_status"]["invalid"] == 1
    assert ext["pages_by_text_source"] == {"text_layer": 2}
    assert o["window"]["processing"]["by_status"] == {"succeeded": 2} and o["window"]["processing"]["failure_rate"] == 0


def test_scope_follows_application_access_type_and_synthetic_flag(world, session_factory):
    owner = world["owner"]
    kyc = make_app(owner, "KYC", ["03 March 1990"])
    make_app(owner, "Loan", ["03 March 1990"], app_type="loan")
    assert overview(world["outsider"])["scope"]["applications"] == 0
    assert overview(world["auditor"])["scope"]["applications"] == 2
    admin_view = overview(world["author"])
    assert admin_view["scope"]["applications"] == 2
    assert admin_view["current"]["documents"]["total"] == 2
    assert overview(owner, application_type="loan")["current"]["applications"]["total"] == 1
    with session_factory() as s:
        s.get(Application, kyc["id"]).is_synthetic = True
        s.commit()
    o = overview(owner)
    assert o["scope"]["synthetic_applications"] == 1 and o["current"]["applications"]["synthetic"] == 1
    assert overview(owner, include_synthetic="false")["scope"]["applications"] == 1
    listed = {a["title"]: a["is_synthetic"] for a in owner.get(f"{API}/applications").json()["items"]}
    assert listed == {"KYC": True, "Loan": False}


# ------------------------------------------------------------------ date windows


def test_date_window_filters_history_but_not_current_state(world, session_factory):
    owner = world["owner"]
    app = make_app(owner, "Old application", ["01 January 2015"])
    validate(owner, app["id"])
    ten_days_ago = datetime.now(UTC) - timedelta(days=10)
    with session_factory() as s:
        s.get(Application, app["id"]).created_at = ten_days_ago
        s.commit()

    o = overview(owner, **{"from": str(TODAY - timedelta(days=13)), "to": str(TODAY)})
    created = o["window"]["applications_created"]
    assert created["total"] == 1 and len(created["by_day"]) == 14
    assert next(d for d in created["by_day"] if d["count"])["date"] == ten_days_ago.date().isoformat()

    recent = overview(owner, **{"from": str(TODAY - timedelta(days=2)), "to": str(TODAY)})
    assert recent["window"]["applications_created"]["total"] == 0
    assert recent["window"]["validation"]["runs"] == 1

    past = overview(owner, **{"from": "2020-01-01", "to": "2020-01-31"})
    assert past["window"]["validation"]["runs"] == 0 and past["window"]["validation"]["cases"]["applications"] == 0
    assert past["window"]["processing"]["finished"] == 0
    # Current state ignores the window.
    assert past["current"]["findings"]["by_outcome"] == {"fail": 1} and past["current"]["applications"]["total"] == 1

    assert owner.get(f"{API}/insights/overview", params={"from": "2026-02-01", "to": "2026-01-01"}).status_code == 422
    assert owner.get(f"{API}/insights/overview", params={"from": "2024-01-01", "to": "2026-01-01"}).status_code == 422


def test_review_backlog_workload_and_false_positives(world):
    owner = world["owner"]
    for title in ("Case one", "Case two", "Case three"):
        app = make_app(owner, title, ["01 January 2015"])
        validate(owner, app["id"])
    items = sorted((r["item"] for r in owner.get(f"{API}/reviews").json()["items"]), key=lambda i: i["id"])
    one, two, three = items
    act(owner, one, "assigned", assignee_id=world["ids"]["owner"])
    act(owner, two, "confirmed", reason="Minor confirmed by source")
    dismissed = act(owner, three, "dismissed", reason="Synthetic test document, not a real minor")

    r = owner.get(f"{API}/insights/review").json()
    assert r["backlog"]["total"] == 1 and r["backlog"]["by_age"]["under_1_day"] == 1 and r["backlog"]["unassigned"] == 0
    assert r["workload"] == [{"user_id": world["ids"]["owner"], "full_name": "Test reviewer",
                              "email": "owner@example.org", "count": 1, "by_severity": {"high": 1}}]
    fp = r["false_positives"]
    assert (fp["decided_items"], fp["confirmed"], fp["dismissed"], fp["rate"]) == (2, 1, 1, 0.5)
    assert fp["by_rule"][0]["rule_key"] == "adult_applicant" and fp["by_rule"][0]["false_positive_rate"] == 0.5
    assert fp["by_category"] == {"failure": {"confirmed": 1, "dismissed": 1, "false_positive_rate": 0.5}}
    o = overview(owner)
    assert o["current"]["human"] == {"confirmed": 1, "dismissed": 1}
    assert o["window"]["review"] == {"opened": 3, "confirmed": 1, "dismissed": 1}

    # Reopening a dismissal withdraws it from the false-positive count until it is decided again.
    act(owner, dismissed, "reopened", reason="New evidence to look at")
    fp = owner.get(f"{API}/insights/review").json()["false_positives"]
    assert (fp["decided_items"], fp["dismissed"], fp["rate"], fp["reopened_excluded"]) == (1, 0, 0.0, 1)
    past = owner.get(f"{API}/insights/review", params={"from": "2020-01-01", "to": "2020-01-31"}).json()
    assert past["false_positives"]["decided_items"] == 0 and past["backlog"]["total"] == 2


# ------------------------------------------------------------------ pagination and history


def test_validation_history_and_rule_governance_pagination(world):
    owner = world["owner"]
    app = make_app(owner, "Paged", ["03 March 1990"])
    for _ in range(3):
        validate(owner, app["id"])
    page = owner.get(f"{API}/insights/rules", params={"limit": 2, "offset": 0}).json()["runs"]
    assert page["total"] == 3 and len(page["items"]) == 2
    rest = owner.get(f"{API}/insights/rules", params={"limit": 2, "offset": 2}).json()["runs"]
    assert len(rest["items"]) == 1
    assert {i["run_id"] for i in page["items"]}.isdisjoint({i["run_id"] for i in rest["items"]})

    g = owner.get(f"{API}/insights/rule-governance").json()
    assert g["counts"] == {"created": 1, "submitted": 1, "approved": 1} and g["total"] == 3
    approved = next(e for e in g["items"] if e["event"] == "approved")
    assert approved["four_eyes"] is True and approved["actor"]["email"] == "approver@example.org"
    assert [e["event"] for e in g["items"]] == ["approved", "submitted", "created"]
    second = owner.get(f"{API}/insights/rule-governance", params={"limit": 1, "offset": 1}).json()
    assert [e["event"] for e in second["items"]] == ["submitted"] and second["total"] == 3
    assert owner.get(f"{API}/insights/rule-governance",
                     params={"from": "2020-01-01", "to": "2020-01-02"}).json()["total"] == 0


def test_audit_history_filters_and_pagination(world):
    owner, auditor = world["owner"], world["auditor"]
    make_app(owner, "Audited", ["03 March 1990"])
    rules = auditor.get(f"{API}/audit/events", params={"action": "rule."}).json()
    assert rules["total"] >= 3 and all(e["action"].startswith("rule.") for e in rules["items"])
    assert not any(e["action"].startswith("application.") for e in rules["items"])
    exact = auditor.get(f"{API}/audit/events", params={"action": "application.created"}).json()
    assert exact["total"] == 1 and exact["items"][0]["summary"].startswith("Created application")
    assert auditor.get(f"{API}/audit/events", params={"q": "created application"}).json()["total"] == 1
    assert auditor.get(f"{API}/audit/events", params={"from": "2020-01-01", "to": "2020-01-02"}).json()["total"] == 0
    today = auditor.get(f"{API}/audit/events", params={"from": str(TODAY), "to": str(TODAY)}).json()
    everything = auditor.get(f"{API}/audit/events").json()
    assert today["total"] == everything["total"] > 5
    p1 = auditor.get(f"{API}/audit/events", params={"limit": 3, "offset": 0}).json()
    p2 = auditor.get(f"{API}/audit/events", params={"limit": 3, "offset": 3}).json()
    assert [e["seq"] for e in p1["items"]] == sorted([e["seq"] for e in p1["items"]], reverse=True)
    assert p1["items"][-1]["seq"] > p2["items"][0]["seq"]
    owner.post(f"{API}/exports", json={"dataset": "audit_events"})  # refused: reviewer lacks exports:create
    failures = auditor.get(f"{API}/audit/events", params={"outcome": "failure"}).json()
    assert failures["total"] >= 1 and all(e["outcome"] == "failure" for e in failures["items"])
    assert "application.created" in auditor.get(f"{API}/audit/actions").json()
    assert owner.get(f"{API}/audit/events").status_code == 403


# ------------------------------------------------------------------ exports


def test_export_authorization_by_role(world, session_factory):
    owner, auditor, manager = world["owner"], world["auditor"], world["manager"]
    make_app(owner, "Exported", ["03 March 1990"])
    assert export(owner, dataset="metrics_summary").status_code == 403
    datasets = {d["key"]: d for d in auditor.get(f"{API}/exports/datasets").json()}
    assert datasets["audit_events"]["allowed"] and not datasets["extracted_fields"]["allowed"]

    ok = export(auditor, dataset="review_items", format="csv")
    assert ok.status_code == 200 and ok.headers["content-type"].startswith("text/csv")
    assert "attachment" in ok.headers["content-disposition"]

    # Sensitive: role, explicit opt-in and a reason are all required, and refusals are audited.
    assert export(auditor, dataset="extracted_fields").status_code == 403
    assert export(manager, dataset="extracted_fields").status_code == 403
    assert export(manager, dataset="extracted_fields", include_document_values=True).status_code == 403
    assert export(manager, dataset="extracted_fields", include_document_values=True, reason="short").status_code == 403
    sensitive_audit = export(auditor, dataset="audit_events", include_document_values=True, reason="Investigating case")
    assert sensitive_audit.status_code == 403
    with session_factory() as s:
        denied = s.execute(select(AuditEvent).where(AuditEvent.action == "export.denied")).scalars().all()
    assert len(denied) == 5 and all(e.outcome == "failure" for e in denied)

    r = export(manager, dataset="extracted_fields", format="csv", include_document_values=True,
               reason="Quarterly extraction quality review")
    assert r.status_code == 200 and int(r.headers["x-export-rows"]) == 8
    rows = list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig"))))
    assert any(row["raw_value"] == "03 March 1990" for row in rows)
    assert "page_text" not in rows[0] and "raw_text" not in rows[0]
    with session_factory() as s:
        ev = s.execute(select(AuditEvent).where(AuditEvent.action == "export.created")
                       .order_by(AuditEvent.seq.desc())).scalars().first()
    assert ev.data["contains_document_values"] is True and ev.data["reason"] == "Quarterly extraction quality review"
    assert ev.data["sha256"] == hashlib.sha256(r.content).hexdigest() and ev.seq == int(r.headers["x-export-audit-seq"])


def test_audit_export_omits_event_data_unless_sensitive(world):
    auditor, manager = world["auditor"], world["manager"]
    r = export(auditor, dataset="audit_events", format="json", action="rule.")
    body = r.json()
    assert body["meta"]["contains_document_values"] is False and body["rows"]
    assert all("data" not in row for row in body["rows"])
    assert all(row["action"].startswith("rule.") for row in body["rows"])
    r = export(manager, dataset="audit_events", format="json", include_document_values=True,
               reason="Investigating a reported change")
    assert all("data" in row for row in r.json()["rows"])


def test_exports_are_scoped_deduplicated_and_injection_safe(world):
    owner, manager = world["owner"], world["manager"]
    app = make_app(owner, "Formula", ["01 January 2015"])
    pdf = factories.labelled_pdf([["Full name: =HYPERLINK(1)", "Date of birth: 03 March 1990"]])
    owner.post(f"{API}/applications/{app['id']}/documents", files={"file": ("f.pdf", pdf, "application/pdf")})
    for _ in range(2):
        validate(owner, app["id"])
    results = export(manager, dataset="validation_results", format="json").json()
    assert results["meta"]["rows"] == 1 and results["rows"][0]["outcome"] == "fail"
    assert "raw_value" not in results["rows"][0]
    r = export(manager, dataset="extracted_fields", format="csv", include_document_values=True,
               reason="Checking export escaping")
    cells = [row["raw_value"] for row in csv.DictReader(io.StringIO(r.content.decode("utf-8-sig")))]
    assert "'=HYPERLINK(1)" in cells and "=HYPERLINK(1)" not in cells

    summary = export(manager, dataset="metrics_summary", format="json").json()
    assert {d["key"] for d in summary["definitions"]} >= {"findings.current", "review.false_positive_rate"}
    assert summary["overview"]["current"]["findings"]["by_outcome"] == {"fail": 1}
    flat = {row["metric"]: row["value"] for row in summary["rows"]}
    assert flat["current.findings.engine_failures"] == 1 and flat["window.validation.runs"] == 2


def test_export_events_are_immutable_and_chain_stays_valid(world, session_factory):
    assert export(world["auditor"], dataset="rule_history", format="csv").status_code == 200
    with session_factory() as s:
        ev = s.execute(select(AuditEvent).where(AuditEvent.action == "export.created")).scalar_one()
        ev.summary = "nothing to see"
        with pytest.raises(AuditImmutableError):
            s.commit()
    with session_factory() as s, pytest.raises(Exception, match="append-only"):
        s.execute(text("UPDATE audit_events SET summary = 'x' WHERE action = 'export.created'"))
    with session_factory() as s, pytest.raises(Exception, match="append-only"):
        s.execute(text("DELETE FROM audit_events WHERE action = 'export.created'"))
    assert world["auditor"].get(f"{API}/audit/verify").json()["valid"] is True


# ------------------------------------------------------------------ synthetic demo data


def test_seed_demo_creates_labelled_synthetic_data_through_the_real_pipeline(world, session_factory, storage):
    rows = demo_seed.seed_demo(session_factory, storage, "owner@example.org")
    assert len(rows) == 3 and all(r["title"].startswith("[SYNTHETIC DEMO]") for r in rows)
    o = overview(world["owner"])
    assert o["scope"]["synthetic_applications"] == 3 and o["current"]["applications"]["synthetic"] == 3
    # Real pipeline output, not invented numbers: one application per case, documents extracted, runs recorded.
    assert o["current"]["documents"]["total"] == 5 and o["current"]["extraction"]["documents_with_current_run"] == 5
    assert o["window"]["validation"]["runs"] == 3
    assert overview(world["owner"], include_synthetic="false")["scope"]["applications"] == 0
    with session_factory() as s:
        assert s.execute(select(AuditEvent).where(AuditEvent.action == "demo.seeded")).scalar_one()
    with pytest.raises(demo_seed.SeedRefused):
        demo_seed.seed_demo(session_factory, storage, "nobody@example.org")
    with pytest.raises(demo_seed.SeedRefused):
        demo_seed.seed_demo(session_factory, storage, "auditor@example.org")


def test_definitions_document_every_metric(world):
    defs = world["auditor"].get(f"{API}/insights/definitions").json()
    keys = {d["key"] for d in defs}
    assert {"findings.current", "validation.runs", "validation.cases", "review.false_positive_rate",
            "extraction.correction_rate", "rules.governance"} <= keys
    for d in defs:
        assert d["definition"] and d["source"] and d["basis"] in ("current", "window")
        assert (d["basis"] == "window") == bool(d["time_field"])
    assert json.dumps(defs)  # serializable as documented
