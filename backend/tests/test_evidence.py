"""Cross-document evidence analysis end to end: outcomes, provenance, priority, reproducibility, permissions."""

from __future__ import annotations

import pytest
from sqlalchemy import select, update

from app.core.roles import Role
from app.extraction.ocr import get_ocr_engine
from app.main import app as fastapi_app
from app.models.evidence import EvidenceFinding, ImmutableEvidenceError
from app.models.extraction import ExtractedField, ExtractionRun
from tests import factories
from tests.test_extraction import FakeOcr

API = "/api/v1"

BASE = {
    "Full name": "Test Person Alpha",
    "Date of birth": "03 March 1990",
    "National ID": "TEST-0001-AB",
    "Document number": "SYN 000123",
}


def lines(overrides: dict | None = None, address: list[str] | None = None, drop: tuple[str, ...] = ()) -> list[str]:
    values = {**BASE, **(overrides or {})}
    out = [f"{k}: {v}" for k, v in values.items() if k not in drop]
    if address:
        out += [f"Address: {address[0]}", *address[1:]]
    return out


@pytest.fixture
def alice(make_user, login):
    make_user(Role.REVIEWER, email="alice@example.org")
    return login("alice@example.org")


@pytest.fixture
def app_id(alice) -> str:
    return alice.post(
        f"{API}/applications", json={"title": "Synthetic evidence case", "application_type": "kyc"}
    ).json()["id"]


def upload(c, app_id: str, content: bytes, name: str) -> dict:  # noqa: ANN001
    r = c.post(f"{API}/applications/{app_id}/documents", files={"file": (name, content, "application/pdf")})
    assert r.status_code == 201, r.text
    return r.json()


def analyze(c, app_id: str, force: bool = False):  # noqa: ANN001, ANN201
    return c.post(f"{API}/applications/{app_id}/evidence/analyses", json={"force": force})


def findings(view: dict) -> dict[str, dict]:
    return {f["group_key"]: f for f in view["findings"]}


ADDRESS = ["1 Synthetic Street", "Testville", "TS1 0AA"]


# ------------------------------------------------------------------ equivalent values / false mismatches


def test_equivalent_values_across_formats_pass_with_listed_normalizations(alice, app_id):
    upload(alice, app_id, factories.labelled_pdf([lines(address=ADDRESS)]), "passport.pdf")
    upload(
        alice,
        app_id,
        factories.labelled_pdf(
            [
                lines(
                    {"Full name": "TEST PERSON ALPHA", "Date of birth": "1990-03-03", "National ID": "TEST 0001 AB"},
                    address=["1 synthetic street,", "TESTVILLE", "TS1 0AA"],
                )
            ]
        ),
        "statement.pdf",
    )
    r = analyze(alice, app_id)
    assert r.status_code == 201, r.text
    f = findings(r.json())
    for key in ("person_name", "date_of_birth", "national_id", "address", "document_number"):
        assert f[key]["outcome"] == "pass", (key, f[key]["explanation"])
    rel = f["person_name"]["relationships"][0]
    assert rel["method"] == "approved_normalization" and rel["details"]["normalizations"] == ["case"]
    assert f["date_of_birth"]["relationships"][0]["method"] == "exact"  # both normalized to 1990-03-03
    assert f["national_id"]["relationships"][0]["details"]["normalizations"] == ["separators"]
    assert f["person_name"]["priority_score"] == 0


# ------------------------------------------------------------------ contradictions


def test_contradictory_fields_are_confirmed_fails_with_traceable_evidence(alice, app_id, session_factory):
    a = upload(alice, app_id, factories.labelled_pdf([lines()]), "passport.pdf")
    b = upload(
        alice, app_id, factories.labelled_pdf([["Intro page"], lines({"Date of birth": "04 April 1985"})]), "form.pdf"
    )
    view = analyze(alice, app_id).json()
    dob = findings(view)["date_of_birth"]
    assert dob["outcome"] == "fail" and dob["severity"] == "critical" and dob["evidence_quality"] == "high"
    rel = dob["relationships"][0]
    assert (rel["result"], rel["reason"]) == ("fail", "different_values")

    refs = {r["id"]: r for r in dob["references"]}
    src, tgt = refs[rel["source_reference_id"]], refs[rel["target_reference_id"]]
    assert {src["document_id"], tgt["document_id"]} == {a["id"], b["id"]}
    assert tgt["page_number"] == 2 and tgt["effective_value"] == "1985-04-04" and tgt["raw_value"] == "04 April 1985"
    # Provenance: every reference points at a real extracted field of that document's current run.
    with session_factory() as s:
        for ref in dob["references"]:
            field = s.get(ExtractedField, ref["extracted_field_id"])
            run = s.get(ExtractionRun, ref["extraction_run_id"])
            assert field.document_id == ref["document_id"] and field.run_id == run.id and run.is_current
            assert field.page_number == ref["page_number"] and field.bbox == ref["bbox"]
            assert field.raw_value == ref["raw_value"]
    # Explanation is generated from the stored evidence.
    assert "passport.pdf" in rel["explanation"] and "form.pdf" in rel["explanation"]
    assert "1990-03-03" in rel["explanation"] and "1985-04-04" in rel["explanation"]
    # Priority factors are shown and add up.
    assert dob["priority_score"] == sum(f["contribution"] for f in dob["priority_factors"])
    factors = {f["factor"]: f["contribution"] for f in dob["priority_factors"]}
    assert factors == {"severity": 40, "outcome": 30, "evidence_quality": 10, "breadth": 5, "impact": 10}
    assert view["analysis"]["summary"]["fail"] >= 1


def test_near_miss_names_are_review_not_fail(alice, app_id):
    upload(alice, app_id, factories.labelled_pdf([lines()]), "a.pdf")
    upload(alice, app_id, factories.labelled_pdf([lines({"Full name": "Test Persn Alpha"})]), "b.pdf")
    name = findings(analyze(alice, app_id).json())["person_name"]
    assert name["outcome"] == "review" and name["relationships"][0]["reason"] == "near_match"


# ------------------------------------------------------------------ OCR noise


def test_low_confidence_ocr_difference_is_not_a_confirmed_contradiction(alice, app_id):
    upload(alice, app_id, factories.labelled_pdf([lines()]), "clean.pdf")
    noisy = lines({"Full name": "Tost Porsan Alpho", "National ID": "TEST-OOO1-AB"})
    fastapi_app.dependency_overrides[get_ocr_engine] = lambda: FakeOcr(noisy, confidence=45.0)
    upload(alice, app_id, factories.labelled_pdf([noisy], scanned=True), "scan.pdf")
    f = findings(analyze(alice, app_id).json())
    name = f["person_name"]
    assert name["outcome"] == "review" and name["evidence_quality"] == "low"
    rel = name["relationships"][0]
    assert rel["reason"] == "low_quality_evidence" and rel["details"]["comparator_result"] == "fail"
    nid = f["national_id"]
    assert nid["outcome"] == "review" and nid["relationships"][0]["reason"] in (
        "possible_ocr_confusion",
        "low_quality_evidence",
    )
    assert all(x["outcome"] != "fail" for x in f.values() if x["evidence_quality"] == "low")


def test_good_quality_ocr_can_confirm_a_contradiction(alice, app_id):
    upload(alice, app_id, factories.labelled_pdf([lines()]), "clean.pdf")
    scanned = lines({"Date of birth": "15 August 1985"})
    fastapi_app.dependency_overrides[get_ocr_engine] = lambda: FakeOcr(scanned, confidence=95.0)
    upload(alice, app_id, factories.labelled_pdf([scanned], scanned=True), "scan.pdf")
    dob = findings(analyze(alice, app_id).json())["date_of_birth"]
    assert dob["outcome"] == "fail" and dob["evidence_quality"] == "medium"


# ------------------------------------------------------------------ missing values and documents


def test_missing_values_and_single_sources_are_insufficient(alice, app_id):
    upload(alice, app_id, factories.labelled_pdf([lines(address=ADDRESS)]), "a.pdf")
    upload(alice, app_id, factories.labelled_pdf([lines(drop=("National ID",))]), "b.pdf")
    f = findings(analyze(alice, app_id).json())
    addr = f["address"]
    assert (
        addr["outcome"] == "insufficient" and addr["coverage"]["with_value"] == 1 and addr["coverage"]["missing"] == 1
    )
    assert addr["relationships"][0]["result"] == "insufficient" and addr["relationships"][0]["evidence_quality"] is None
    nid = f["national_id"]
    assert nid["outcome"] == "insufficient" and nid["relationships"][0]["reason"] == "missing_value"
    assert f["person_name"]["outcome"] == "pass"  # unaffected by other gaps
    # No document has an account number: the gaps are listed, but no value-less comparisons are invented.
    acct = f["account_number"]
    assert acct["outcome"] == "insufficient" and acct["relationships"] == [] and len(acct["references"]) == 2


def test_gaps_do_not_turn_agreement_into_failure(alice, app_id):
    for name in ("a.pdf", "b.pdf"):
        upload(alice, app_id, factories.labelled_pdf([lines()]), name)
    upload(alice, app_id, factories.labelled_pdf([lines(drop=("Full name",))]), "c.pdf")
    name = findings(analyze(alice, app_id).json())["person_name"]
    assert name["outcome"] == "pass" and name["coverage"] == {
        "documents": 3,
        "with_value": 2,
        "missing": 1,
        "invalid": 0,
        "not_extracted": 0,
        "min_values": 2,
    }
    assert "c.pdf" in name["explanation"]


def test_unextracted_documents_are_reported(alice, app_id, session_factory):
    upload(alice, app_id, factories.labelled_pdf([lines()]), "a.pdf")
    b = upload(alice, app_id, factories.labelled_pdf([lines()]), "b.pdf")
    with session_factory() as s:
        s.execute(update(ExtractionRun).where(ExtractionRun.document_id == b["id"]).values(is_current=False))
        s.commit()
    name = findings(analyze(alice, app_id).json())["person_name"]
    assert name["outcome"] == "insufficient" and name["coverage"]["not_extracted"] == 1
    gap = next(r for r in name["references"] if r["document_id"] == b["id"])
    assert gap["status"] == "not_extracted" and gap["extracted_field_id"] is None and gap["usable"] is False


def test_application_without_documents_cannot_be_analyzed(alice, app_id):
    r = analyze(alice, app_id)
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_documents"
    assert alice.get(f"{API}/applications/{app_id}/evidence").json()["error"]["code"] == "not_analyzed"


def test_invalid_values_are_insufficient_not_contradictions(alice, app_id):
    upload(alice, app_id, factories.labelled_pdf([lines()]), "a.pdf")
    upload(alice, app_id, factories.labelled_pdf([lines({"Date of birth": "31/02/1990"})]), "b.pdf")
    dob = findings(analyze(alice, app_id).json())["date_of_birth"]
    assert dob["outcome"] == "insufficient" and dob["relationships"][0]["reason"] == "invalid_value"


def test_ambiguous_date_match_requires_review(alice, app_id):
    upload(alice, app_id, factories.labelled_pdf([lines({"Date of birth": "1990-04-03"})]), "a.pdf")
    upload(alice, app_id, factories.labelled_pdf([lines({"Date of birth": "03/04/1990"})]), "b.pdf")
    dob = findings(analyze(alice, app_id).json())["date_of_birth"]
    assert dob["outcome"] == "review" and dob["relationships"][0]["reason"] == "ambiguous_input"


# ------------------------------------------------------------------ corrections, staleness, reproducibility


def test_reproducible_reuse_force_and_staleness(alice, app_id, session_factory):
    upload(alice, app_id, factories.labelled_pdf([lines()]), "a.pdf")
    b = upload(alice, app_id, factories.labelled_pdf([lines({"Date of birth": "04 April 1985"})]), "b.pdf")
    first = analyze(alice, app_id)
    assert first.status_code == 201
    again = analyze(alice, app_id)
    assert (
        again.status_code == 200
        and again.json()["reused"]
        and again.json()["analysis"]["id"] == first.json()["analysis"]["id"]
    )

    forced = analyze(alice, app_id, force=True)
    assert forced.status_code == 201 and forced.json()["analysis"]["id"] != first.json()["analysis"]["id"]
    assert forced.json()["analysis"]["input_fingerprint"] == first.json()["analysis"]["input_fingerprint"]

    def strip(view: dict) -> list:
        return [
            (
                f["group_key"],
                f["outcome"],
                f["priority_score"],
                f["explanation"],
                [(r["result"], r["reason"], r["explanation"]) for r in f["relationships"]],
            )
            for f in view["findings"]
        ]

    assert strip(forced.json()) == strip(first.json())  # same inputs -> identical results

    # A human correction makes the stored analysis stale but never changes it.
    view = alice.get(f"{API}/applications/{app_id}/documents/{b['id']}/extraction").json()
    dob_field = next(x for x in view["fields"] if x["field_key"] == "date_of_birth")
    alice.post(
        f"{API}/applications/{app_id}/documents/{b['id']}/extraction/fields/{dob_field['id']}/corrections",
        json={"value": "1990-03-03", "reason": "Verified against original"},
    )
    stale = alice.get(f"{API}/applications/{app_id}/evidence").json()
    assert stale["stale"] is True and findings(stale)["date_of_birth"]["outcome"] == "fail"

    fresh = analyze(alice, app_id).json()
    dob = findings(fresh)["date_of_birth"]
    assert dob["outcome"] == "pass" and fresh["stale"] is False
    corrected = next(r for r in dob["references"] if r["document_id"] == b["id"])
    assert (
        corrected["value_source"] == "correction"
        and corrected["correction_id"]
        and corrected["raw_value"] == "04 April 1985"
    )

    old = alice.get(f"{API}/applications/{app_id}/evidence/analyses/{first.json()['analysis']['id']}").json()
    assert findings(old)["date_of_birth"]["outcome"] == "fail" and old["analysis"]["is_current"] is False
    history = alice.get(f"{API}/applications/{app_id}/evidence/analyses").json()
    assert sum(a["is_current"] for a in history) == 1 and len(history) == 3

    with session_factory() as s:
        row = s.execute(select(EvidenceFinding)).scalars().first()
        row.outcome = "pass"
        with pytest.raises(ImmutableEvidenceError):
            s.flush()


def test_new_document_makes_analysis_stale(alice, app_id):
    upload(alice, app_id, factories.labelled_pdf([lines()]), "a.pdf")
    analyze(alice, app_id)
    upload(alice, app_id, factories.labelled_pdf([lines()]), "b.pdf")
    assert alice.get(f"{API}/applications/{app_id}/evidence").json()["stale"] is True


# ------------------------------------------------------------------ permissions and isolation


def test_permissions_and_isolation(alice, app_id, make_user, login):
    upload(alice, app_id, factories.labelled_pdf([lines()]), "a.pdf")
    upload(alice, app_id, factories.labelled_pdf([lines()]), "b.pdf")
    analyze(alice, app_id)
    url = f"{API}/applications/{app_id}/evidence"
    make_user(Role.REVIEWER, email="bob@example.org")
    bob = login("bob@example.org")
    assert bob.get(url).status_code == 404 and analyze(bob, app_id).status_code == 404
    alice.post(f"{API}/applications/{app_id}/members", json={"email": "bob@example.org", "role": "viewer"})
    assert bob.get(url).status_code == 200 and analyze(bob, app_id).status_code == 403
    make_user(Role.AUDITOR, email="audrey@example.org")
    audrey = login("audrey@example.org")
    view = audrey.get(url).json()
    assert view["can_analyze"] is False and analyze(audrey, app_id).status_code == 403
    # Isolation: another application's evidence never references these documents.
    other = alice.post(f"{API}/applications", json={"title": "Other synthetic case", "application_type": "kyc"}).json()[
        "id"
    ]
    upload(alice, other, factories.labelled_pdf([lines()]), "x.pdf")
    other_view = analyze(alice, other).json()
    docs = {r["document_name"] for f in other_view["findings"] for r in f["references"]}
    assert docs == {"x.pdf"}
