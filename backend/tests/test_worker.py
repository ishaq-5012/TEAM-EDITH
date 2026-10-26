"""Durable processing worker: queue-only API in worker mode, single execution across workers, stale recovery."""

from __future__ import annotations

import threading
from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from app.core.config import get_settings
from app.core.roles import Role
from app.db.base import utcnow
from app.extraction.ocr import UnavailableOcrEngine
from app.models import AuditEvent, Document, ProcessingJob
from app.models.extraction import ExtractionRun
from app.services import worker
from tests import factories

API = "/api/v1"
OCR = UnavailableOcrEngine("OCR disabled in tests")


@pytest.fixture
def worker_mode(monkeypatch):
    monkeypatch.setenv("VERIFYFLOW_PROCESSING_MODE", "worker")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def alice(make_user, login):
    make_user(Role.REVIEWER, email="alice@example.org")
    return login("alice@example.org")


def _upload(c, name: str = "a.pdf") -> tuple[str, str]:  # noqa: ANN001
    app = c.post(f"{API}/applications", json={"title": "Synthetic worker case", "application_type": "kyc"}).json()
    content = factories.labelled_pdf(
        [["Full name: Test Person Alpha", "Date of birth: 03 March 1990", f"Note: {name}"]]
    )
    doc = c.post(f"{API}/applications/{app['id']}/documents", files={"file": (name, content, "application/pdf")})
    assert doc.status_code == 201, doc.text
    return app["id"], doc.json()["id"]


def _doc(c, app_id: str, doc_id: str) -> dict:  # noqa: ANN001
    return c.get(f"{API}/applications/{app_id}/documents/{doc_id}").json()


def test_api_only_queues_in_worker_mode_and_the_worker_processes(worker_mode, alice, session_factory, storage):
    app_id, doc_id = _upload(alice)
    assert _doc(alice, app_id, doc_id)["status"] == "queued"  # the API did not process it
    assert worker.run_once(session_factory, storage, OCR) == 1
    d = _doc(alice, app_id, doc_id)
    assert d["status"] == "ready" and d["jobs"][-1]["status"] == "succeeded"
    fields = alice.get(f"{API}/applications/{app_id}/documents/{doc_id}/extraction").json()["fields"]
    assert next(f for f in fields if f["field_key"] == "full_name")["normalized_value"] == "Test Person Alpha"
    assert worker.run_once(session_factory, storage, OCR) == 0  # nothing left


def test_inline_mode_is_unchanged(alice):
    app_id, doc_id = _upload(alice)
    assert _doc(alice, app_id, doc_id)["status"] == "ready"


def test_concurrent_workers_run_each_job_once(worker_mode, alice, session_factory, storage):
    ids = [_upload(alice, f"doc-{i}.pdf") for i in range(3)]
    barrier = threading.Barrier(3)

    def go() -> None:
        barrier.wait()
        worker.run_once(session_factory, storage, OCR)

    threads = [threading.Thread(target=go) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    with session_factory() as s:
        assert s.execute(select(func.count()).select_from(ExtractionRun)).scalar_one() == 3
        assert s.execute(select(func.count()).select_from(ProcessingJob)).scalar_one() == 3
    assert all(_doc(alice, a, d)["status"] == "ready" for a, d in ids)


def _strand(session_factory, attempt: int = 1) -> None:  # noqa: ANN001
    """Simulate a worker that died mid-job."""
    with session_factory() as s:
        s.execute(
            update(ProcessingJob).values(status="running", started_at=utcnow() - timedelta(hours=2), attempt=attempt)
        )
        s.execute(update(Document).values(status="processing"))
        s.commit()


def test_interrupted_job_is_requeued_audited_and_completed(worker_mode, alice, session_factory, storage):
    app_id, doc_id = _upload(alice)
    _strand(session_factory)
    assert worker.recover_stale(session_factory) == 1
    jobs = _doc(alice, app_id, doc_id)["jobs"]
    assert [(j["status"], j["error_code"]) for j in jobs] == [("failed", "interrupted"), ("queued", None)]
    assert worker.run_once(session_factory, storage, OCR) == 1
    d = _doc(alice, app_id, doc_id)
    assert d["status"] == "ready" and d["jobs"][-1]["status"] == "succeeded"
    with session_factory() as s:
        ev = s.execute(select(AuditEvent).where(AuditEvent.action == "document.processing_recovered")).scalar_one()
        assert ev.data["requeued"] is True and ev.data["attempt"] == 1


def test_recovery_stops_at_the_attempt_limit(worker_mode, alice, session_factory, storage):
    app_id, doc_id = _upload(alice)
    _strand(session_factory, attempt=get_settings().processing_max_attempts)
    assert worker.recover_stale(session_factory) == 1
    d = _doc(alice, app_id, doc_id)
    assert d["status"] == "failed" and len(d["jobs"]) == 1 and d["can_retry"] is True
    assert worker.run_once(session_factory, storage, OCR) == 0


def test_recent_running_jobs_are_left_alone(worker_mode, alice, session_factory):
    _upload(alice)
    with session_factory() as s:
        s.execute(update(ProcessingJob).values(status="running", started_at=utcnow()))
        s.commit()
    assert worker.recover_stale(session_factory) == 0


def test_a_failing_pass_does_not_stop_the_worker(monkeypatch, session_factory, storage):
    calls = []

    def boom(*_a, **_k):  # noqa: ANN002, ANN003, ANN202
        calls.append(1)
        if len(calls) >= 2:
            stop.set()
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(worker, "run_once", boom)
    monkeypatch.setenv("VERIFYFLOW_WORKER_POLL_SECONDS", "0.1")
    get_settings.cache_clear()
    stop = threading.Event()
    worker.run_forever(session_factory, storage, stop)
    get_settings.cache_clear()
    assert len(calls) == 2


def test_readiness_shows_the_backlog_a_stopped_worker_leaves(worker_mode, alice, client, session_factory, storage):
    _upload(alice)
    p = client.get(f"{API}/health/ready").json()["processing"]
    assert p["mode"] == "worker" and p["queued"] == 1 and p["oldest_queued_seconds"] >= 0
    worker.run_once(session_factory, storage, OCR)
    assert client.get(f"{API}/health/ready").json()["processing"]["queued"] == 0
