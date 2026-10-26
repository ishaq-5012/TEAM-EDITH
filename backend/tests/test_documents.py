"""Document upload validation, storage, processing, retry and authorized download."""

from __future__ import annotations

import hashlib
from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from app.core.roles import Role
from app.db.base import utcnow
from app.main import app as fastapi_app
from app.models.application import Document, ProcessingJob
from app.models.audit import AuditEvent
from app.services import document_service, processing
from app.services.storage import LocalStorage, get_storage
from tests import factories

API = "/api/v1"


@pytest.fixture
def alice(make_user, login):
    make_user(Role.REVIEWER, email="alice@example.org")
    return login("alice@example.org")


@pytest.fixture
def app_id(alice) -> str:
    r = alice.post(f"{API}/applications", json={"title": "Synthetic document case", "application_type": "onboarding"})
    return r.json()["id"]


def upload(c, app_id: str, content: bytes, name: str = "synthetic.pdf", mime: str | None = "application/pdf", **data):  # noqa: ANN001, ANN201
    file = (name, content, mime) if mime is not None else (name, content)
    return c.post(f"{API}/applications/{app_id}/documents", files={"file": file}, data=data or None)


def stored_files(storage: LocalStorage) -> list:
    return [p for p in storage.root.rglob("*") if p.is_file()]


def doc_rows(session_factory) -> int:  # noqa: ANN001
    with session_factory() as s:
        return s.execute(select(func.count()).select_from(Document)).scalar_one()


# ------------------------------------------------------------------ valid uploads


def test_pdf_upload_is_stored_privately_hashed_and_processed(alice, app_id, storage):
    content = factories.pdf(pages=2)
    r = upload(alice, app_id, content, "Synthetic Statement.PDF", document_type="bank_statement")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["sha256"] == hashlib.sha256(content).hexdigest()
    assert body["size_bytes"] == len(content)
    assert body["detected_mime"] == "application/pdf" and body["page_count"] == 2
    assert body["document_type"] == "bank_statement"
    assert "storage_key" not in body and "path" not in str(body).lower()

    files = stored_files(storage)
    assert len(files) == 1
    assert files[0].name not in content.decode("latin-1") and "Synthetic" not in files[0].name
    assert files[0].suffix == "" and len(files[0].name) == 48  # random internal name, no client input
    assert files[0].read_bytes() == content

    detail = alice.get(f"{API}/applications/{app_id}/documents/{body['id']}").json()
    assert detail["status"] == "ready"
    job = detail["jobs"][0]
    assert job["status"] == "succeeded" and job["attempt"] == 1
    assert job["result"]["facts"]["text_layer"] == "full"


def test_png_and_jpeg_uploads(alice, app_id):
    png = upload(alice, app_id, factories.png(), "scan.png", "image/png")
    jpg = upload(alice, app_id, factories.jpeg(), "photo.JPEG", "image/jpeg")
    assert png.status_code == jpg.status_code == 201
    detail = alice.get(f"{API}/applications/{app_id}/documents/{png.json()['id']}").json()
    # No OCR in tests: an image yields no text, which is surfaced for review rather than reported as "ready".
    assert detail["status"] == "needs_review"
    assert detail["jobs"][0]["result"]["facts"]["width"] == 120
    assert [f["code"] for f in detail["jobs"][0]["result"]["findings"]] == ["ocr_required"]


def test_undeclared_mime_is_accepted_when_content_and_extension_agree(alice, app_id):
    assert upload(alice, app_id, factories.pdf(), "x.pdf", "application/octet-stream").status_code == 201


def test_scanned_pdf_reports_missing_text_layer(alice, app_id):
    doc = upload(alice, app_id, factories.pdf(pages=2, text=False)).json()
    detail = alice.get(f"{API}/applications/{app_id}/documents/{doc['id']}").json()
    assert detail["status"] == "needs_review"  # no text layer and OCR unavailable
    assert detail["jobs"][0]["result"]["facts"]["text_layer"] == "none"
    assert detail["jobs"][0]["result"]["findings"][0]["code"] == "ocr_required"


@pytest.mark.parametrize(
    "kwargs,code", [({"javascript": True}, "pdf_javascript"), ({"embedded": True}, "pdf_embedded_files")]
)
def test_active_content_needs_review(alice, app_id, kwargs, code):
    doc = upload(alice, app_id, factories.pdf(**kwargs)).json()
    detail = alice.get(f"{API}/applications/{app_id}/documents/{doc['id']}").json()
    assert detail["status"] == "needs_review"
    assert code in [f["code"] for f in detail["jobs"][0]["result"]["findings"]]


# ------------------------------------------------------------------ invalid uploads


@pytest.mark.parametrize(
    "content,name,mime,status,code",
    [
        (factories.png(), "invoice.pdf", "application/pdf", 415, "extension_mismatch"),  # PNG pretending to be PDF
        (factories.pdf(), "photo.png", "image/png", 415, "extension_mismatch"),
        (factories.pdf(), "statement.pdf", "image/png", 415, "mime_mismatch"),  # lying Content-Type
        (factories.pdf(), "statement", "application/pdf", 415, "extension_mismatch"),  # no extension
        (b"MZ\x90\x00" + b"\x00" * 200, "invoice.pdf", "application/pdf", 415, "unsupported_file_type"),  # executable
        (b"<html><script>alert(1)</script></html>", "page.pdf", "application/pdf", 415, "unsupported_file_type"),
        (b"plain text that is not a document", "notes.txt", "text/plain", 415, "unsupported_file_type"),
        (b"", "empty.pdf", "application/pdf", 400, "empty_file"),
        (b"%PDF-1.7\n" + b"\x00garbage" * 50, "broken.pdf", "application/pdf", 422, None),
        (factories.pdf(encrypted=True), "locked.pdf", "application/pdf", 422, "pdf_encrypted"),
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "corrupt.png", "image/png", 422, "image_invalid"),
    ],
)
def test_rejected_uploads_leave_nothing_behind(alice, app_id, storage, session_factory, content, name, mime, status,
                                               code):
    r = upload(alice, app_id, content, name, mime)
    assert r.status_code == status, r.text
    if code:
        assert r.json()["error"]["code"] == code
    else:
        assert r.json()["error"]["code"] in {"pdf_invalid", "pdf_empty"}
    assert stored_files(storage) == []
    assert doc_rows(session_factory) == 0
    with session_factory() as s:
        ev = s.execute(select(AuditEvent).where(AuditEvent.action == "document.upload_rejected")).scalar_one()
        assert ev.outcome == "failure"


def test_page_limit_enforced(alice, app_id, monkeypatch, storage):
    settings = document_service.get_settings().model_copy(update={"max_pdf_pages": 2})
    monkeypatch.setattr(document_service, "get_settings", lambda: settings)
    r = upload(alice, app_id, factories.pdf(pages=3))
    assert r.status_code == 422 and r.json()["error"]["code"] == "pdf_too_many_pages"
    assert stored_files(storage) == []


def test_oversized_file_rejected_by_streaming_limit(alice, app_id, storage, tmp_path):
    small = LocalStorage(root=storage.root, max_bytes=2048)
    fastapi_app.dependency_overrides[get_storage] = lambda: small
    r = upload(alice, app_id, factories.pdf(pages=5) + b"\n%" + b"x" * 4096)
    assert r.status_code == 413 and r.json()["error"]["code"] == "file_too_large"
    assert stored_files(storage) == []


def test_oversized_request_rejected_before_body_is_read(alice, app_id, monkeypatch, storage):
    from app.api.routes import applications as routes

    settings = routes.get_settings().model_copy(update={"max_upload_bytes": 1024})
    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    r = upload(alice, app_id, b"%PDF-" + b"x" * 200_000)
    assert r.status_code == 413 and r.json()["error"]["code"] == "file_too_large"
    assert stored_files(storage) == []


def test_missing_file_part_and_wrong_content_type(alice, app_id):
    r = alice.post(f"{API}/applications/{app_id}/documents", data={"document_type": "x"},
                   files={"other": ("a.pdf", b"%PDF-", "application/pdf")})
    assert r.status_code == 422 and r.json()["error"]["code"] == "file_required"
    r = alice.post(f"{API}/applications/{app_id}/documents", json={"file": "base64?"})
    assert r.status_code == 415


def test_chunked_upload_without_length_is_refused(alice, app_id):
    def body():
        yield b"--x\r\n"

    r = alice.post(f"{API}/applications/{app_id}/documents", content=body(),
                   headers={"Content-Type": "multipart/form-data; boundary=x"})
    assert r.status_code == 411


def test_upload_requires_csrf_token(alice, app_id, storage):
    token = alice.headers.pop("X-CSRF-Token")
    assert upload(alice, app_id, factories.pdf()).status_code == 403
    alice.headers["X-CSRF-Token"] = token
    assert stored_files(storage) == []


# ------------------------------------------------------------------ duplicates


def test_duplicate_hash_rejected_within_application(alice, app_id, storage):
    content = factories.pdf(marker="dup")
    first = upload(alice, app_id, content, "original.pdf")
    assert first.status_code == 201
    second = upload(alice, app_id, content, "renamed copy.pdf")
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "duplicate_document"
    assert "original.pdf" in second.json()["error"]["message"]
    assert len(stored_files(storage)) == 1

    other = alice.post(f"{API}/applications", json={"title": "Another synthetic case", "application_type": "loan"})
    assert upload(alice, other.json()["id"], content, "original.pdf").status_code == 201


# ------------------------------------------------------------------ storage failures


class _BrokenStorage(LocalStorage):
    def save(self, stream):  # noqa: ANN001, ANN201
        raise OSError(28, "No space left on device")


def test_storage_write_failure_returns_503_and_records_nothing(alice, app_id, storage, session_factory):
    fastapi_app.dependency_overrides[get_storage] = lambda: _BrokenStorage(root=storage.root)
    r = upload(alice, app_id, factories.pdf())
    assert r.status_code == 503 and r.json()["error"]["code"] == "storage_unavailable"
    assert "No space" not in r.text  # internal error detail stays in the server log
    assert doc_rows(session_factory) == 0
    with session_factory() as s:
        assert s.execute(select(AuditEvent).where(AuditEvent.action == "document.upload_failed")).scalar_one()


def test_database_failure_after_write_removes_stored_file(alice, app_id, storage, monkeypatch):
    def boom(*_a, **_k):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError("simulated database failure")

    monkeypatch.setattr(document_service.application_service, "mark_processing", boom)
    with pytest.raises(RuntimeError):
        upload(alice, app_id, factories.pdf())
    assert stored_files(storage) == []


def test_missing_stored_file_is_404_and_tampered_file_is_refused(alice, app_id, storage, session_factory):
    doc = upload(alice, app_id, factories.pdf()).json()
    path = stored_files(storage)[0]
    path.write_bytes(path.read_bytes() + b"tampered")
    r = alice.get(f"{API}/applications/{app_id}/documents/{doc['id']}/content")
    assert r.status_code == 500 and r.json()["error"]["code"] == "integrity_failure"
    with session_factory() as s:
        assert s.execute(select(AuditEvent).where(AuditEvent.action == "document.integrity_failed")).scalar_one()
    path.unlink()
    assert alice.get(f"{API}/applications/{app_id}/documents/{doc['id']}/content").status_code == 404


# ------------------------------------------------------------------ processing failures and retry


def test_processing_failure_and_retry(alice, app_id, monkeypatch):
    original = processing._inspect_pdf
    monkeypatch.setattr(processing, "_inspect_pdf", lambda path: (_ for _ in ()).throw(RuntimeError("parser crashed")))
    doc = upload(alice, app_id, factories.pdf()).json()
    detail = alice.get(f"{API}/applications/{app_id}/documents/{doc['id']}").json()
    assert detail["status"] == "failed" and detail["can_retry"] is True
    assert detail["jobs"][0]["error_code"] == "processing_error"
    assert "parser crashed" in detail["jobs"][0]["error_message"]
    assert alice.get(f"{API}/applications/{app_id}").json()["status"] == "needs_review"

    monkeypatch.setattr(processing, "_inspect_pdf", original)
    r = alice.post(f"{API}/applications/{app_id}/documents/{doc['id']}/retry")
    assert r.status_code == 200
    detail = alice.get(f"{API}/applications/{app_id}/documents/{doc['id']}").json()
    assert detail["status"] == "ready"
    assert [(j["attempt"], j["status"]) for j in detail["jobs"]] == [(1, "failed"), (2, "succeeded")]
    assert alice.post(f"{API}/applications/{app_id}/documents/{doc['id']}/retry").status_code == 409


def test_integrity_mismatch_during_processing_fails_job(alice, app_id, storage, monkeypatch):
    monkeypatch.setattr(LocalStorage, "read", lambda self, key: b"%PDF-1.7 bytes that do not match the stored hash")
    doc = upload(alice, app_id, factories.pdf()).json()
    detail = alice.get(f"{API}/applications/{app_id}/documents/{doc['id']}").json()
    assert detail["status"] == "failed" and detail["jobs"][0]["error_code"] == "integrity_mismatch"


def test_stale_running_job_can_be_retried(alice, app_id, session_factory):
    doc = upload(alice, app_id, factories.pdf()).json()
    with session_factory() as s:
        s.execute(update(ProcessingJob).values(status="running", started_at=utcnow() - timedelta(hours=2),
                                               finished_at=None))
        s.execute(update(Document).values(status="processing"))
        s.commit()
    assert alice.get(f"{API}/applications/{app_id}/documents/{doc['id']}").json()["can_retry"] is True
    assert alice.post(f"{API}/applications/{app_id}/documents/{doc['id']}/retry").status_code == 200
    jobs = alice.get(f"{API}/applications/{app_id}/documents/{doc['id']}").json()["jobs"]
    assert jobs[0]["error_code"] == "interrupted" and jobs[1]["status"] == "succeeded"


# ------------------------------------------------------------------ download authorization


def test_authorized_download_headers_and_body(alice, app_id):
    content = factories.pdf(marker="download")
    doc = upload(alice, app_id, content, "Synthetic Résumé.pdf").json()
    r = alice.get(f"{API}/applications/{app_id}/documents/{doc['id']}/content")
    assert r.status_code == 200
    assert r.content == content
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"].startswith("attachment;")
    assert "sandbox" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-document-sha256"] == hashlib.sha256(content).hexdigest()
    assert "no-store" in r.headers["cache-control"]


def test_unauthorized_downloads(alice, app_id, client, make_user, login):
    doc = upload(alice, app_id, factories.pdf()).json()
    url = f"{API}/applications/{app_id}/documents/{doc['id']}/content"
    assert client.get(url).status_code == 401  # anonymous
    make_user(Role.REVIEWER, email="mallory@example.org")
    assert login("mallory@example.org").get(url).status_code == 404  # other reviewer
    make_user(Role.AUDITOR, email="audrey@example.org")
    assert login("audrey@example.org").get(url).status_code == 200  # read-all oversight


def test_downloads_are_audited(alice, app_id, session_factory):
    doc = upload(alice, app_id, factories.pdf()).json()
    alice.get(f"{API}/applications/{app_id}/documents/{doc['id']}/content")
    with session_factory() as s:
        ev = s.execute(select(AuditEvent).where(AuditEvent.action == "document.downloaded")).scalar_one()
        assert ev.data["document_id"] == doc["id"] and ev.actor_email == "alice@example.org"


def test_upload_limits_endpoint(alice):
    limits = alice.get(f"{API}/applications/upload-limits").json()
    assert limits["accepted"]["application/pdf"] == [".pdf"]
    assert limits["max_upload_bytes"] > 0
