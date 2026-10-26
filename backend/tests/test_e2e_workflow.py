"""End-to-end synthetic workflow (Phase 12): every step goes through the public API, as the SPA would call it.

1 authenticate · 2 create an application · 3 upload two synthetic documents · 4 extract fields · 5 compare fields
across documents · 6 produce a traceable compliance finding · 7 send an uncertain finding to human review ·
8 correct an extracted value with a reason · 9 trigger a new validation run · 10 verify old and new results stay
linked · 11 inspect trust-verification status · 12 review the audit trail · 13 check dashboard metrics against the
persisted records.
"""

from __future__ import annotations

from app.core.roles import Role
from tests import factories

API = "/api/v1"
ON = "2026-10-23"


def _publish(author, manager, key: str, condition: dict, **definition) -> dict:  # noqa: ANN001
    r = author.post(
        f"{API}/rules",
        json={
            "key": key,
            "name": f"E2E {key}",
            "category": "eligibility",
            "effective_from": "2026-01-01",
            "definition": {"condition": condition, "severity": "high", **definition},
            "source_reference": "Synthetic policy SYN-E2E",
            "change_summary": "Initial",
        },
    )
    assert r.status_code == 201, r.text
    rule = r.json()
    vid = rule["versions"][0]["id"]
    assert author.post(f"{API}/rules/{rule['id']}/versions/{vid}/submit").status_code == 200
    assert (
        manager.post(f"{API}/rules/{rule['id']}/versions/{vid}/approve", json={"note": "four-eyes ok"}).status_code
        == 200
    )
    return rule


def test_synthetic_workflow_end_to_end(make_user, login, client):
    # 1. Authenticate. Anonymous calls are refused; each person gets their own session and CSRF token.
    assert client.get(f"{API}/applications").status_code == 401
    make_user(Role.ADMIN, email="author@example.org")
    make_user(Role.COMPLIANCE_MANAGER, email="manager@example.org")
    make_user(Role.SECOND_APPROVER, email="approver@example.org")
    make_user(Role.REVIEWER, email="reviewer@example.org")
    admin = login("author@example.org")
    author, manager, reviewer = (login(f"{n}@example.org") for n in ("manager", "approver", "reviewer"))
    me = reviewer.get(f"{API}/auth/me").json()
    assert me["role"] == "reviewer"

    # Two published rules: a hard eligibility rule, and a consistency rule that routes doubt to a person.
    _publish(
        author,
        manager,
        "adult_applicant",
        {"field": "extracted.date_of_birth", "op": "age_years_at_least", "value": 18},
    )
    _publish(
        author,
        manager,
        "name_consistent",
        {"field": "evidence.person_name.outcome", "op": "eq", "value": "pass"},
        on_violation="review",
    )

    # 2. Create an application.
    r = reviewer.post(f"{API}/applications", json={"title": "E2E synthetic onboarding", "application_type": "kyc"})
    assert r.status_code == 201, r.text
    app = r.json()
    aid = app["id"]

    # 3. Upload two synthetic documents. The second has a near-miss name and a mistyped date of birth.
    docs = {}
    for name, full_name, dob in (
        ("passport.pdf", "Test Person Alpha", "03 March 1990"),
        ("utility-bill.pdf", "Test Persn Alpha", "01 January 2015"),
    ):
        content = factories.labelled_pdf(
            [[f"Full name: {full_name}", f"Date of birth: {dob}", "National ID: TEST-0001-AB"]]
        )
        r = reviewer.post(f"{API}/applications/{aid}/documents", files={"file": (name, content, "application/pdf")})
        assert r.status_code == 201, r.text
        docs[name] = r.json()
        assert len(docs[name]["sha256"]) == 64
    listed = reviewer.get(f"{API}/applications/{aid}/documents").json()
    assert {d["original_filename"] for d in listed} == set(docs) and all(d["status"] == "ready" for d in listed)

    # 4. Extract fields, with raw value, normalized value and source location (provenance).
    fields = {}
    for name, d in docs.items():
        view = reviewer.get(f"{API}/applications/{aid}/documents/{d['id']}/extraction").json()
        fields[name] = {f["field_key"]: f for f in view["fields"]}
    bill_dob = fields["utility-bill.pdf"]["date_of_birth"]
    assert (bill_dob["raw_value"], bill_dob["normalized_value"]) == ("01 January 2015", "2015-01-01")
    assert bill_dob["page_number"] == 1 and len(bill_dob["bbox"]) == 4
    assert fields["passport.pdf"]["full_name"]["normalized_value"] == "Test Person Alpha"

    # 5. Compare corresponding fields across documents.
    r = reviewer.post(f"{API}/applications/{aid}/evidence/analyses", json={"force": False})
    assert r.status_code in (200, 201), r.text
    evidence = {f["group_key"]: f for f in r.json()["findings"]}
    assert evidence["person_name"]["outcome"] == "review"
    assert evidence["person_name"]["relationships"][0]["reason"] == "near_match"
    assert evidence["date_of_birth"]["outcome"] == "fail"

    # 6. A traceable compliance finding: each result names its rule version and the evidence it read.
    r = reviewer.post(f"{API}/applications/{aid}/validation-runs", json={"evaluation_date": ON})
    assert r.status_code == 201, r.text
    first = r.json()
    assert first["summary"]["fail"] == 1 and first["summary"]["review"] == 1
    run = reviewer.get(f"{API}/applications/{aid}/validation-runs/{first['id']}").json()
    results = {x["rule_key"]: x for x in run["results"]}
    adult = results["adult_applicant"]
    assert adult["outcome"] == "fail" and adult["rule_version_id"]
    assert adult["trace"], "a failing result must carry its rule-to-evidence trace"
    assert "2015-01-01" in str(adult["trace"])
    assert results["name_consistent"]["outcome"] == "review"
    # The stored snapshot reproduces the same outcomes.
    repro = reviewer.get(f"{API}/applications/{aid}/validation-runs/{first['id']}/reproduction").json()
    assert (repro["identical"], repro["snapshot_intact"], repro["differences"]) == (True, True, [])

    # 7. The uncertain finding is in the review queue as its own item; the reviewer takes it.
    queue = reviewer.get(f"{API}/reviews", params={"application_id": aid}).json()
    items = {i["item"]["category"]: i["item"] for i in queue["items"]}
    assert set(items) == {"failure", "uncertain"}
    uncertain = items["uncertain"]
    r = reviewer.post(
        f"{API}/reviews/{uncertain['id']}/actions",
        json={"action": "assigned", "expected_version": uncertain["version"], "assignee_id": me["id"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["item"]["assignee"]["id"] == me["id"]

    # 8. Correct the mistyped date of birth with a reason, from the failure item. The original stays.
    failure = items["failure"]
    r = reviewer.post(
        f"{API}/reviews/{failure['id']}/corrections",
        json={
            "expected_version": failure["version"],
            "document_id": docs["utility-bill.pdf"]["id"],
            "field_id": bill_dob["id"],
            "value": "1990-03-03",
            "reason": "Typo on the synthetic bill; passport shows 1990",
            "request_id": "e2e-correction-1",
        },
    )
    assert r.status_code == 200, r.text
    corrected = r.json()
    assert (
        corrected["action"]["data"]["before"] == "2015-01-01" and corrected["action"]["data"]["after"] == "1990-03-03"
    )
    assert corrected["action"]["data"]["original_extraction"]["raw_value"] == "01 January 2015"
    view = reviewer.get(f"{API}/applications/{aid}/documents/{docs['utility-bill.pdf']['id']}/extraction").json()
    dob = next(f for f in view["fields"] if f["field_key"] == "date_of_birth")
    assert dob["raw_value"] == "01 January 2015" and dob["effective_value"] == "1990-03-03"
    assert dob["corrections"][0]["reason"].startswith("Typo")

    # 9. The correction revalidated automatically; a manual run is still possible and is linked too.
    reval = corrected["revalidation"]
    assert reval["performed"] and reval["previous_run_id"] == first["id"]
    r = reviewer.post(f"{API}/applications/{aid}/validation-runs", json={"evaluation_date": ON})
    assert r.status_code == 201, r.text
    third = r.json()

    # 10. Previous and new results remain linked, and the first run is unchanged.
    old = reviewer.get(f"{API}/applications/{aid}/validation-runs/{first['id']}").json()
    assert old["summary"]["fail"] == 1 and reval["run_id"] in old["next_run_ids"]
    second = reviewer.get(f"{API}/applications/{aid}/validation-runs/{reval['run_id']}").json()
    assert {x["rule_key"]: x["outcome"] for x in second["results"]}["adult_applicant"] == "pass"
    runs = reviewer.get(f"{API}/applications/{aid}/validation-runs").json()
    assert [x["id"] for x in runs][:3] == [third["id"], reval["run_id"], first["id"]]
    detail = reviewer.get(f"{API}/reviews/{failure['id']}").json()
    assert [h["action"] for h in detail["history"]] == ["opened", "field_corrected", "revalidated"]
    assert [x["outcome"] for x in detail["rule_runs"]][-1] == "fail"

    # 11. Trust status: the file hash is verified; an unsigned PDF is never reported as authentic.
    r = reviewer.post(f"{API}/applications/{aid}/documents/{docs['passport.pdf']['id']}/verifications")
    assert r.status_code == 201, r.text
    trust = r.json()
    assert trust["summary"]["file_integrity"] == "verified"
    assert trust["summary"]["signature_integrity"] != "verified"
    assert trust["recorded_sha256"] == trust["observed_sha256"] == docs["passport.pdf"]["sha256"]

    # 12. The audit trail recorded each step, and its hash chain is intact.
    events = admin.get(f"{API}/audit/events", params={"limit": 200}).json()["items"]
    actions = {e["action"] for e in events}
    for expected in ("auth.login", "application.created", "document.uploaded", "review.field_corrected"):
        assert any(a == expected or a.startswith(expected) for a in actions), (expected, sorted(actions))
    assert any(a.startswith("validation") for a in actions) and any(a.startswith("trust") for a in actions)
    chain = admin.get(f"{API}/audit/verify").json()
    assert chain["valid"] is True
    assert reviewer.get(f"{API}/audit/events").status_code == 403

    # 13. Dashboard metrics come from the persisted records above.
    o = reviewer.get(f"{API}/insights/overview").json()
    assert o["current"]["applications"]["total"] == 1 and o["current"]["documents"]["total"] == 2
    assert o["window"]["validation"]["runs"] == 3
    assert o["window"]["validation"]["by_trigger"] == {"manual": 2, "correction": 1}
    assert o["current"]["review"]["backlog"] == 1 and o["current"]["review"]["backlog_by_category"] == {"uncertain": 1}
    assert o["current"]["extraction"]["correction_rate"]["corrected"] == 1
