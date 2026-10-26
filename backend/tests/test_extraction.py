"""Extraction pipeline: text layer, OCR states, coordinates, normalization, idempotency, concurrency, corrections."""

from __future__ import annotations

import io

import pytest
import pymupdf
from PIL import Image
from sqlalchemy import func, select, update

from app.core.roles import Role
from app.extraction.ocr import OcrFailed, OcrResult, OcrWord, get_ocr_engine
from app.main import app as fastapi_app
from app.models.application import JobStatus, ProcessingJob
from app.models.extraction import ExtractedField, ExtractionRun, ImmutableRecordError
from app.services import processing
from tests import factories

API = "/api/v1"

PERSON = [
    "Full name: Test Person Alpha",
    "Date of birth: 03 March 1990",
    "National ID: test-0001-ab",
    "Document number: SYN 000123",
    "Address: 1 Synthetic Street",
    "Testville",
    "TS1 0AA",
]


def test_portal_table_extracts_institution_fields_without_personal_identity_fields():
    from app.extraction.definitions import load_definitions
    from app.extraction.ocr import UnavailableOcrEngine
    from app.extraction.pipeline import run

    pdf = pymupdf.open()
    page = pdf.new_page()
    for y, label, value in (
        (100, "Institution name", "Demo Technical Institute"),
        (120, "Institution reference", "INST-DEMO-0042-001"),
        (140, "Target programme", "Applied Electronics (PRG-001-01)"),
        (160, "Existing approved intake", "120"),
        (180, "Proposed intake", "132"),
    ):
        page.insert_text((50, y), label)
        page.insert_text((190, y), value)
    content = pdf.tobytes()
    pdf.close()
    definitions, _ = load_definitions()
    result = run(content, "application/pdf", "programme", definitions, UnavailableOcrEngine(), 0)
    fields = {field.definition.key: field for field in result.fields}
    assert fields["institution_name"].normalized_value == "Demo Technical Institute"
    assert fields["institution_reference"].normalized_value == "INST-DEMO-0042-001"
    assert fields["programme_name"].normalized_value == "Applied Electronics"
    assert fields["programme_name"].raw_value == "Applied Electronics (PRG-001-01)"
    assert fields["current_intake"].normalized_value == "120"
    assert fields["proposed_intake"].normalized_value == "132"
    assert "date_of_birth" not in fields
    assert "national_id" not in fields


def test_portal_inline_programme_and_intake_are_extracted():
    from app.extraction.definitions import load_definitions
    from app.extraction.ocr import UnavailableOcrEngine
    from app.extraction.pipeline import run

    pdf = pymupdf.open()
    pdf.new_page().insert_text((50, 100), "Programme: Computer Science and Engineering; intake: 120.")
    content = pdf.tobytes()
    pdf.close()
    result = run(content, "application/pdf", "programme", load_definitions()[0], UnavailableOcrEngine(), 0)
    fields = {field.definition.key: field for field in result.fields}
    assert fields["programme_name"].normalized_value == "Computer Science and Engineering"
    assert fields["current_intake"].normalized_value == "120"


class FakeOcr:
    """Deterministic OCR double. Returns `lines` laid out like labelled_pdf(): each line at (72, 100 + 18i) pt."""

    def __init__(self, lines: list[str], confidence: float = 92.0, fail: bool = False, name: str = "fake-ocr-1"):
        self.lines, self.confidence, self.fail, self.name = lines, confidence, fail, name
        self.calls = 0

    def available(self) -> bool:
        return True

    def recognize(self, image: Image.Image) -> OcrResult:
        self.calls += 1
        if self.fail:
            raise OcrFailed("simulated OCR crash")
        scale = image.width / 595  # pixels per point of the rendered displayed page
        words = []
        for i, line in enumerate(self.lines):
            x, baseline = 72.0, 100 + i * 18
            for token in line.split(" "):
                w = len(token) * 6.0
                words.append(
                    OcrWord(
                        token, x * scale, (baseline - 10) * scale, w * scale, 12 * scale, self.confidence, f"1.1.{i}"
                    )
                )
                x += w + 3
        return OcrResult(words)


@pytest.fixture
def alice(make_user, login):
    make_user(Role.REVIEWER, email="alice@example.org")
    return login("alice@example.org")


@pytest.fixture
def app_id(alice) -> str:
    return alice.post(
        f"{API}/applications", json={"title": "Synthetic extraction case", "application_type": "kyc"}
    ).json()["id"]


def use_ocr(engine) -> None:  # noqa: ANN001
    fastapi_app.dependency_overrides[get_ocr_engine] = lambda: engine


def upload(c, app_id: str, content: bytes, name: str = "synthetic.pdf", mime: str = "application/pdf") -> dict:  # noqa: ANN001
    r = c.post(f"{API}/applications/{app_id}/documents", files={"file": (name, content, mime)})
    assert r.status_code == 201, r.text
    return r.json()


def extraction(c, app_id: str, doc_id: str) -> dict:  # noqa: ANN001
    r = c.get(f"{API}/applications/{app_id}/documents/{doc_id}/extraction")
    assert r.status_code == 200, r.text
    return r.json()


def fields(view: dict) -> dict[str, dict]:
    return {f["field_key"]: f for f in view["fields"]}


def ink_in_bbox(c, app_id: str, doc_id: str, page: int, bbox: list[float], scale: float = 2.0) -> float:  # noqa: ANN001
    """Fraction of dark pixels inside the bbox on the server-rendered page (same space as stored coordinates)."""
    r = c.get(f"{API}/applications/{app_id}/documents/{doc_id}/pages/{page}/image", params={"scale": scale})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    img = Image.open(io.BytesIO(r.content)).convert("L")
    x0, y0, x1, y1 = (round(v * scale) for v in bbox)
    crop = img.crop((x0, y0, x1, y1))
    dark = sum(1 for p in crop.getdata() if p < 128)
    return dark / max(1, crop.width * crop.height)


# ------------------------------------------------------------------ text layer


def test_text_layer_fields_with_raw_normalized_and_coordinates(alice, app_id):
    doc = upload(alice, app_id, factories.labelled_pdf([PERSON]))
    view = extraction(alice, app_id, doc["id"])
    assert view["run"]["status"] == "succeeded" and view["run"]["is_current"]
    assert view["extractor"]["kind"] == "deterministic_baseline" and "synthetic" in view["extractor"]["limitations"]
    page = view["pages"][0]
    assert page | {"warnings": []} == page | {
        "page_number": 1,
        "width": 595.0,
        "height": 842.0,
        "rotation": 0,
        "units": "pt",
        "text_source": "text_layer",
        "text_layer_quality": "good",
        "ocr_status": "not_needed",
        "warnings": [],
    }

    f = fields(view)
    assert f["full_name"]["raw_value"] == "Test Person Alpha" and f["full_name"]["status"] == "found"
    assert f["date_of_birth"]["raw_value"] == "03 March 1990"
    assert f["date_of_birth"]["normalized_value"] == "1990-03-03"
    assert f["date_of_birth"]["normalized_data"] == {"iso": "1990-03-03"}
    assert f["national_id"]["raw_value"] == "test-0001-ab" and f["national_id"]["normalized_value"] == "TEST-0001-AB"
    assert f["document_number"]["normalized_value"] == "SYN 000123"
    assert f["address"]["raw_value"] == "1 Synthetic Street\nTestville\nTS1 0AA"
    assert f["address"]["normalized_data"] == {"lines": ["1 Synthetic Street", "Testville", "TS1 0AA"]}
    assert f["full_name"]["method"] == "text_layer_rule" and f["full_name"]["matched_label"] == "Full name"

    # Coordinates: the name value starts after "Full name: " on the line whose baseline is y=100.
    x0, y0, x1, y1 = f["full_name"]["bbox"]
    assert 110 < x0 < 140 and 85 < y0 < 100 and 98 < y1 < 106 and x1 > x0
    assert ink_in_bbox(alice, app_id, doc["id"], 1, f["full_name"]["bbox"]) > 0.05
    # The address box spans its three lines.
    assert f["address"]["bbox"][3] - f["address"]["bbox"][1] > 36


def test_raw_page_text_is_preserved_and_normalized_separately(alice, app_id):
    doc = upload(alice, app_id, factories.labelled_pdf([["Full name:    Spaced    Out   Person"]]))
    r = alice.get(f"{API}/applications/{app_id}/documents/{doc['id']}/pages/1/text").json()
    assert "Spaced    Out" in r["raw_text"]
    assert "Spaced Out Person" in r["normalized_text"] and "  " not in r["normalized_text"]
    assert fields(extraction(alice, app_id, doc["id"]))["full_name"]["normalized_value"] == "Spaced Out Person"


def test_field_on_second_page(alice, app_id):
    doc = upload(
        alice,
        app_id,
        factories.labelled_pdf([["Intro text only, nothing labelled here."], ["Account number: ACCT-0042"]]),
    )
    f = fields(extraction(alice, app_id, doc["id"]))["account_number"]
    assert f["page_number"] == 2 and f["normalized_value"] == "ACCT-0042"
    assert ink_in_bbox(alice, app_id, doc["id"], 2, f["bbox"]) > 0.05


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_rotated_pages_use_displayed_coordinates(alice, app_id, rotation):
    doc = upload(alice, app_id, factories.labelled_pdf([["Full name: Rotated Page Person"]], rotation=rotation))
    view = extraction(alice, app_id, doc["id"])
    page = view["pages"][0]
    assert page["rotation"] == rotation
    if rotation in (90, 270):
        assert (page["width"], page["height"]) == (842.0, 595.0)
    f = fields(view)["full_name"]
    x0, y0, x1, y1 = f["bbox"]
    assert 0 <= x0 < x1 <= page["width"] and 0 <= y0 < y1 <= page["height"]
    if rotation in (90, 270):
        assert (y1 - y0) > (x1 - x0)  # a horizontal line of text becomes vertical on screen
    assert ink_in_bbox(alice, app_id, doc["id"], 1, f["bbox"]) > 0.05


def test_missing_fields_are_reported_not_guessed(alice, app_id):
    doc = upload(
        alice, app_id, factories.labelled_pdf([["Full name: Only Name Present", "Some unlabeled 12/12/2020 text"]])
    )
    f = fields(extraction(alice, app_id, doc["id"]))
    assert f["full_name"]["status"] == "found"
    for key in ("date_of_birth", "issue_date", "national_id", "address"):
        assert f[key]["status"] == "missing"
        assert f[key]["raw_value"] is None and f[key]["bbox"] is None and f[key]["page_number"] is None


@pytest.mark.parametrize(
    "raw,status,normalized,note",
    [
        ("31/02/2026", "invalid", None, "February 2026 has no day 31"),
        ("2026-13-01", "invalid", None, "Month 13 does not exist"),
        ("12/31/1990", "invalid", None, "Month 31 does not exist"),  # DMY configured
        ("03/04/2026", "ambiguous", "2026-04-03", "ambiguous"),
        ("1 Jan 1850", "invalid", None, "outside the accepted range"),
        ("next Tuesday", "invalid", None, "Not a recognised date format"),
        ("01/02/26", "invalid", None, "Two-digit years"),
        ("15/08/1985", "found", "1985-08-15", None),
        ("August 15, 1985", "found", "1985-08-15", None),
    ],
)
def test_date_normalization_cases(alice, app_id, raw, status, normalized, note):
    doc = upload(alice, app_id, factories.labelled_pdf([[f"Date of birth: {raw}"]]))
    f = fields(extraction(alice, app_id, doc["id"]))["date_of_birth"]
    assert f["raw_value"] == raw  # the source characters survive every outcome
    assert f["status"] == status and f["normalized_value"] == normalized
    if note:
        assert note in f["normalization_note"]
    doc_status = alice.get(f"{API}/applications/{app_id}/documents/{doc['id']}").json()["status"]
    assert doc_status == ("ready" if status == "found" else "needs_review")


def test_conflicting_candidates_are_surfaced(alice, app_id):
    doc = upload(
        alice, app_id, factories.labelled_pdf([["Full name: First Candidate"], ["Full name: Second Candidate"]])
    )
    f = fields(extraction(alice, app_id, doc["id"]))["full_name"]
    assert f["normalized_value"] == "First Candidate"
    assert "conflicting_candidates" in f["quality_flags"]
    assert f["alternatives"][0]["raw_value"] == "Second Candidate" and f["alternatives"][0]["page_number"] == 2


# ------------------------------------------------------------------ scanned pages and OCR states


def test_scanned_pdf_without_ocr_is_explicitly_unavailable(alice, app_id):
    doc = upload(alice, app_id, factories.labelled_pdf([PERSON], scanned=True))
    view = extraction(alice, app_id, doc["id"])
    page = view["pages"][0]
    assert page["text_source"] == "none" and page["text_layer_quality"] == "none"
    assert page["ocr_status"] == "unavailable"
    assert page["warnings"][0]["code"] == "ocr_unavailable"
    assert view["run"]["status"] == "partial"
    f = fields(view)["full_name"]
    assert f["status"] == "missing" and "pages_without_text" in f["quality_flags"]
    assert view["document_status"] == "needs_review"


def test_scanned_pdf_with_ocr_extracts_with_correct_coordinates(alice, app_id):
    engine = FakeOcr(PERSON)
    use_ocr(engine)
    doc = upload(alice, app_id, factories.labelled_pdf([PERSON], scanned=True))
    view = extraction(alice, app_id, doc["id"])
    page = view["pages"][0]
    assert page["text_source"] == "ocr" and page["ocr_status"] == "completed" and page["ocr_confidence"] == 92.0
    assert view["run"]["ocr_engine"] == "fake-ocr-1"
    f = fields(view)
    assert f["full_name"]["method"] == "ocr_rule" and "ocr_source" in f["full_name"]["quality_flags"]
    assert f["date_of_birth"]["normalized_value"] == "1990-03-03"
    # Fake OCR placed "Test" (first value token) at x = 72 + len("Full")*6+3 + len("name:")*6+3 = 132 pt, baseline 100.
    x0, y0, x1, y1 = f["full_name"]["bbox"]
    assert abs(x0 - 132) < 0.5 and abs(y0 - 90) < 0.5 and abs(y1 - 102) < 0.5
    assert ink_in_bbox(alice, app_id, doc["id"], 1, f["full_name"]["bbox"]) > 0.02  # lands on the scanned ink
    assert f["full_name"]["confidence"] == pytest.approx(0.9)


def test_low_confidence_ocr_is_flagged(alice, app_id):
    use_ocr(FakeOcr(PERSON, confidence=41.0))
    doc = upload(alice, app_id, factories.labelled_pdf([PERSON], scanned=True))
    view = extraction(alice, app_id, doc["id"])
    assert view["pages"][0]["ocr_status"] == "low_confidence"
    assert view["pages"][0]["warnings"][0]["code"] == "ocr_low_confidence"
    name = fields(view)["full_name"]
    assert "low_ocr_confidence" in name["quality_flags"] and name["confidence"] == pytest.approx(0.41)
    assert view["document_status"] == "needs_review"


def test_ocr_failure_is_recorded_and_job_still_completes(alice, app_id):
    use_ocr(FakeOcr(PERSON, fail=True))
    doc = upload(alice, app_id, factories.labelled_pdf([PERSON], scanned=True))
    view = extraction(alice, app_id, doc["id"])
    page = view["pages"][0]
    assert page["ocr_status"] == "failed" and page["text_source"] == "none"
    assert "simulated OCR crash" in page["warnings"][0]["message"]
    assert view["run"]["status"] == "partial" and view["document_status"] == "needs_review"


def test_ocr_recognition_errors_are_flagged_never_repaired(alice, app_id):
    ocr_lines = ["Full name: Test Person Alpha", "Date of birth: 3l/O1/199O", "National ID: TEST-OOO1"]
    use_ocr(FakeOcr(ocr_lines))
    doc = upload(alice, app_id, factories.labelled_pdf([ocr_lines], scanned=True))
    f = fields(extraction(alice, app_id, doc["id"]))
    dob = f["date_of_birth"]
    assert dob["status"] == "invalid" and dob["raw_value"] == "3l/O1/199O" and dob["normalized_value"] is None
    assert "possible_ocr_confusion" in dob["quality_flags"]
    nid = f["national_id"]
    assert nid["normalized_value"] == "TEST-OOO1"  # not silently "corrected" to TEST-0001
    assert "possible_ocr_confusion" in nid["quality_flags"]


def test_image_document_uses_pixel_coordinates(alice, app_id):
    lines = ["Full name: Image Person"]
    use_ocr(FakeOcr(lines))
    img = Image.new("RGB", (1190, 1684), "white")  # 2 px per pt of the fake layout
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    doc = upload(alice, app_id, buf.getvalue(), "scan.png", "image/png")
    view = extraction(alice, app_id, doc["id"])
    assert view["pages"][0]["units"] == "px" and view["pages"][0]["width"] == 1190.0
    x0, *_ = fields(view)["full_name"]["bbox"]
    assert abs(x0 - 132 * 2) < 1


def test_garbled_text_layer_assessment():
    from app.extraction.pages import assess_text_layer

    assert assess_text_layer("") == "none"
    assert assess_text_layer("Full name: Test Person Alpha, Date of birth 1990") == "good"
    assert assess_text_layer("Page 1") == "sparse"
    assert assess_text_layer("��� �� abc") == "unusable"
    assert assess_text_layer("%$#@ !!** ^^&& (( )) ~~ ++ ==") == "unusable"


# ------------------------------------------------------------------ idempotency and concurrency


def test_reprocess_is_idempotent_unless_forced(alice, app_id, session_factory):
    doc = upload(alice, app_id, factories.labelled_pdf([PERSON]))
    first = extraction(alice, app_id, doc["id"])["run"]
    base = f"{API}/applications/{app_id}/documents/{doc['id']}"
    assert alice.post(f"{base}/reprocess", json={}).status_code == 202
    again = extraction(alice, app_id, doc["id"])["run"]
    assert again["id"] == first["id"]  # identical key: reused, not recomputed
    assert alice.post(f"{base}/reprocess", json={"force": True}).status_code == 202
    forced = extraction(alice, app_id, doc["id"])["run"]
    assert forced["id"] != first["id"] and forced["idempotency_key"] == first["idempotency_key"]
    runs = alice.get(f"{base}/extraction/runs").json()
    assert [r["is_current"] for r in runs] == [True, False]
    old = alice.get(f"{base}/extraction/runs/{first['id']}").json()
    assert old["run"]["is_current"] is False and fields(old)["full_name"]["raw_value"] == "Test Person Alpha"
    with session_factory() as s:
        assert (
            s.execute(
                select(func.count()).select_from(ExtractionRun).where(ExtractionRun.is_current.is_(True))
            ).scalar_one()
            == 1
        )


def test_new_ocr_engine_changes_the_key_and_reruns(alice, app_id):
    doc = upload(alice, app_id, factories.labelled_pdf([PERSON], scanned=True))
    unavailable = extraction(alice, app_id, doc["id"])["run"]
    use_ocr(FakeOcr(PERSON))  # e.g. Tesseract installed later
    alice.post(f"{API}/applications/{app_id}/documents/{doc['id']}/reprocess", json={})
    after = extraction(alice, app_id, doc["id"])
    assert after["run"]["id"] != unavailable["id"] and after["pages"][0]["text_source"] == "ocr"


def test_only_one_active_job_per_document(alice, app_id, session_factory):
    doc = upload(alice, app_id, factories.labelled_pdf([PERSON]))
    with session_factory() as s:
        s.add(ProcessingJob(document_id=doc["id"], kind="test", status="queued"))
        s.commit()
        with pytest.raises(Exception, match="(?i)unique"):  # SQLite: UNIQUE constraint; PostgreSQL: unique constraint
            s.add(ProcessingJob(document_id=doc["id"], kind="test", status="running"))
            s.commit()
        s.rollback()
        s.execute(update(ProcessingJob).where(ProcessingJob.kind == "test").values(status="failed"))
        s.commit()


def test_concurrent_reprocess_request_is_rejected(alice, app_id, session_factory):
    doc = upload(alice, app_id, factories.labelled_pdf([PERSON]))
    with session_factory() as s:  # another worker's job is in flight
        s.add(ProcessingJob(document_id=doc["id"], kind="other", status="running"))
        s.commit()
    r = alice.post(f"{API}/applications/{app_id}/documents/{doc['id']}/reprocess", json={"force": True})
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_processing"


def test_running_the_same_job_twice_is_a_no_op(alice, app_id, session_factory, storage):
    doc = upload(alice, app_id, factories.labelled_pdf([PERSON]))
    with session_factory() as s:
        job_id = s.execute(select(ProcessingJob.id).where(ProcessingJob.document_id == doc["id"])).scalar_one()
    processing.run_job(job_id, session_factory, storage)  # already succeeded: claim fails, nothing changes
    with session_factory() as s:
        assert s.execute(select(func.count()).select_from(ExtractionRun)).scalar_one() == 1


def test_superseded_job_cannot_overwrite_results(alice, app_id, session_factory, monkeypatch):
    """A worker that lost its claim mid-flight (stale retry took over) must discard its results."""
    real_run = processing.pipeline.run

    def hijacked(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        with session_factory() as s:  # simulate retry marking this job interrupted while it is working
            s.execute(
                update(ProcessingJob)
                .where(ProcessingJob.status == "running")
                .values(status=JobStatus.FAILED.value, error_code="interrupted")
            )
            s.commit()
        return real_run(*args, **kwargs)

    monkeypatch.setattr(processing.pipeline, "run", hijacked)
    doc = upload(alice, app_id, factories.labelled_pdf([PERSON]))
    with session_factory() as s:
        assert s.execute(select(func.count()).select_from(ExtractionRun)).scalar_one() == 0
        job = s.execute(select(ProcessingJob).where(ProcessingJob.document_id == doc["id"])).scalar_one()
        assert job.error_code == "interrupted"  # the late finisher did not overwrite the takeover


# ------------------------------------------------------------------ corrections


def test_corrections_preserve_originals_and_persist_across_runs(alice, app_id, session_factory):
    doc = upload(alice, app_id, factories.labelled_pdf([["Full name: Test Persn Alpha", "Date of birth: 03/04/1990"]]))
    base = f"{API}/applications/{app_id}/documents/{doc['id']}"
    f = fields(extraction(alice, app_id, doc["id"]))
    name_id = f["full_name"]["id"]

    r = alice.post(
        f"{base}/extraction/fields/{name_id}/corrections",
        json={"value": "  Test   Person Alpha ", "reason": "Typo in source"},
    )
    assert r.status_code == 201 and r.json()["normalized_value"] == "Test Person Alpha"
    view = fields(extraction(alice, app_id, doc["id"]))["full_name"]
    assert view["raw_value"] == "Test Persn Alpha" and view["normalized_value"] == "Test Persn Alpha"  # untouched
    assert view["effective_value"] == "Test Person Alpha" and view["effective_source"] == "correction"
    assert view["corrections"][0]["based_on_value"] == "Test Persn Alpha"

    # Ambiguous and invalid corrections are refused.
    dob_id = f["date_of_birth"]["id"]
    bad = alice.post(
        f"{base}/extraction/fields/{dob_id}/corrections", json={"value": "03/04/1990", "reason": "confirm"}
    )
    assert bad.status_code == 422 and "YYYY-MM-DD" in bad.json()["error"]["message"]
    assert (
        alice.post(
            f"{base}/extraction/fields/{dob_id}/corrections", json={"value": "31/02/1990", "reason": "x" * 3}
        ).status_code
        == 422
    )
    ok = alice.post(f"{base}/extraction/fields/{dob_id}/corrections", json={"value": "1990-04-03", "reason": "Checked"})
    assert ok.status_code == 201

    with session_factory() as s:
        row = s.get(ExtractedField, name_id)
        row.raw_value = "tampered"
        with pytest.raises(ImmutableRecordError):
            s.flush()

    alice.post(f"{base}/reprocess", json={"force": True})
    after = fields(extraction(alice, app_id, doc["id"]))["full_name"]
    assert after["id"] != name_id and after["effective_value"] == "Test Person Alpha"
    assert after["correction_based_on_other_value"] is False
    stale = alice.post(f"{base}/extraction/fields/{name_id}/corrections", json={"value": "X Y", "reason": "old run"})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale_field"


def test_correction_permissions(alice, app_id, make_user, login):
    doc = upload(alice, app_id, factories.labelled_pdf([PERSON]))
    fid = fields(extraction(alice, app_id, doc["id"]))["full_name"]["id"]
    url = f"{API}/applications/{app_id}/documents/{doc['id']}/extraction/fields/{fid}/corrections"
    body = {"value": "Someone Else", "reason": "attempt"}
    make_user(Role.REVIEWER, email="bob@example.org")
    bob = login("bob@example.org")
    assert bob.post(url, json=body).status_code == 404
    assert bob.get(f"{API}/applications/{app_id}/documents/{doc['id']}/extraction").status_code == 404
    alice.post(f"{API}/applications/{app_id}/members", json={"email": "bob@example.org", "role": "viewer"})
    assert bob.get(f"{API}/applications/{app_id}/documents/{doc['id']}/extraction").status_code == 200
    assert bob.post(url, json=body).status_code == 403
    make_user(Role.AUDITOR, email="audrey@example.org")
    assert login("audrey@example.org").post(url, json=body).status_code == 403


def test_page_image_endpoint_bounds_and_auth(alice, app_id, client):
    doc = upload(alice, app_id, factories.labelled_pdf([PERSON]))
    base = f"{API}/applications/{app_id}/documents/{doc['id']}/pages"
    assert alice.get(f"{base}/2/image").status_code == 404
    assert alice.get(f"{base}/1/image", params={"scale": 9}).status_code == 422
    assert client.get(f"{base}/1/image").status_code == 401


def test_extraction_404_before_processing(alice, app_id, session_factory):
    doc = upload(alice, app_id, factories.labelled_pdf([PERSON]))
    with session_factory() as s:
        s.execute(update(ExtractionRun).values(is_current=False))
        s.commit()
    r = alice.get(f"{API}/applications/{app_id}/documents/{doc['id']}/extraction")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_extracted"


def _real_tesseract_available() -> bool:
    from app.extraction.ocr import TesseractEngine
    from app.extraction.ocr import get_ocr_engine as real

    return isinstance(real(), TesseractEngine)


@pytest.mark.skipif(not _real_tesseract_available(), reason="Tesseract is not installed on this machine")
def test_real_tesseract_end_to_end(alice, app_id):
    from app.extraction.ocr import get_ocr_engine as real

    use_ocr(real())
    doc = upload(
        alice,
        app_id,
        factories.labelled_pdf(
            [["Full name: Tesseract Person", "Date of birth: 15/08/1985"]], scanned=True, fontsize=14
        ),
    )
    view = extraction(alice, app_id, doc["id"])
    assert view["pages"][0]["text_source"] == "ocr"
    f = fields(view)
    assert f["date_of_birth"]["normalized_value"] == "1985-08-15"
    assert ink_in_bbox(alice, app_id, doc["id"], 1, f["full_name"]["bbox"]) > 0.02


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_multiline_address_on_rotated_pages(alice, app_id, rotation):
    """Regression: address continuation must be judged in reading orientation, not on-screen orientation."""
    doc = upload(alice, app_id, factories.labelled_pdf([PERSON], rotation=rotation))
    f = fields(extraction(alice, app_id, doc["id"]))["address"]
    assert f["raw_value"] == "1 Synthetic Street\nTestville\nTS1 0AA"
    assert ink_in_bbox(alice, app_id, doc["id"], 1, f["bbox"]) > 0.05
