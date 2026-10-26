"""Phase 12 security boundaries across modules: traversal, injection, input limits, cross-user leakage, wrong
source references, concurrency, audit tampering through the API, and migrations from an empty database."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, func, select

from app.core.roles import Role
from app.db.base import Base
from app.models import AuditEvent, Document, FieldCorrection
from tests import factories

API = "/api/v1"
ON = "2026-10-23"
BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture
def people(make_user, login):
    make_user(Role.ADMIN, email="admin@example.org")
    make_user(Role.COMPLIANCE_MANAGER, email="manager@example.org")
    make_user(Role.SECOND_APPROVER, email="approver@example.org")
    make_user(Role.REVIEWER, email="owner@example.org")
    make_user(Role.REVIEWER, email="outsider@example.org")
    return {n: login(f"{n}@example.org") for n in ("admin", "manager", "approver", "owner", "outsider")}


def _app(c, title: str = "Synthetic boundary case") -> dict:  # noqa: ANN001
    r = c.post(f"{API}/applications", json={"title": title, "application_type": "kyc"})
    assert r.status_code == 201, r.text
    return r.json()


def _upload(c, app_id: str, name: str, content: bytes | None = None):  # noqa: ANN001, ANN201
    content = content or factories.labelled_pdf([["Full name: Test Person Alpha", "Date of birth: 03 March 1990"]])
    return c.post(f"{API}/applications/{app_id}/documents", files={"file": (name, content, "application/pdf")})


def _publish_adult_rule(people) -> None:  # noqa: ANN001
    rule = (
        people["manager"]
        .post(
            f"{API}/rules",
            json={
                "key": "adult_applicant",
                "name": "Adult applicant",
                "category": "eligibility",
                "effective_from": "2026-01-01",
                "source_reference": "Synthetic SYN-1",
                "change_summary": "Initial",
                "definition": {
                    "condition": {"field": "extracted.date_of_birth", "op": "age_years_at_least", "value": 18},
                    "severity": "high",
                },
            },
        )
        .json()
    )
    vid = rule["versions"][0]["id"]
    assert people["manager"].post(f"{API}/rules/{rule['id']}/versions/{vid}/submit").status_code == 200
    assert (
        people["approver"].post(f"{API}/rules/{rule['id']}/versions/{vid}/approve", json={"note": "ok ok"}).status_code
        == 200
    )


# ------------------------------------------------------------------ path traversal


@pytest.mark.parametrize(
    ("name", "shown"),
    [
        ("../../../etc/passwd.pdf", "passwd.pdf"),
        ("..\\..\\Windows\\win.ini.pdf", "win.ini.pdf"),
        ("/abs/path/report.pdf", "report.pdf"),
    ],
)
def test_traversal_in_upload_filenames_never_reaches_the_filesystem(people, storage, name, shown):
    app = _app(people["owner"])
    r = _upload(people["owner"], app["id"], name)
    assert r.status_code == 201, r.text
    assert r.json()["original_filename"] == shown
    root = Path(storage.root).resolve()
    stored = [p for p in root.rglob("*") if p.is_file()]
    assert len(stored) == 1 and stored[0].resolve().is_relative_to(root)
    assert shown not in stored[0].name  # the storage key is generated, never derived from the filename


def test_a_name_that_sanitizes_to_no_extension_is_refused(people, storage):
    app = _app(people["owner"])
    r = _upload(people["owner"], app["id"], "../..pdf")
    assert r.status_code == 415 and r.json()["error"]["code"] == "extension_mismatch"
    assert not [p for p in Path(storage.root).rglob("*") if p.is_file()]


@pytest.mark.parametrize(
    "path",
    [
        "/applications/..%2F..%2Fetc/documents",
        "/applications/x/documents/..%2F..%2Fsecret/download",
        "/applications/x/documents/%2e%2e%2f%2e%2e%2fsecret/download",
        "/applications/x/documents/y/pages/..%2F1/image",
    ],
)
def test_traversal_in_ids_is_rejected(people, path):
    r = people["owner"].get(API + path)
    assert r.status_code in (404, 422)
    assert "root:" not in r.text


# ------------------------------------------------------------------ injection and input validation


INJECTIONS = ["' OR '1'='1", "%' OR 1=1 --", "1; DROP TABLE applications;--", '" OR ""="', "_%", "\\"]


@pytest.mark.parametrize("payload", INJECTIONS)
def test_sql_payloads_are_treated_as_plain_text(people, payload):
    owner, admin = people["owner"], people["admin"]
    _app(owner, "Alpha synthetic case")
    _app(owner, "Beta synthetic case")
    for path in ("/applications", "/reviews"):
        r = owner.get(API + path, params={"q": payload})
        assert r.status_code == 200 and r.json()["total"] == 0, (path, r.text)
    assert admin.get(f"{API}/audit/events", params={"q": payload}).status_code == 200
    assert owner.get(f"{API}/applications/{payload}").status_code == 404
    # Nothing was dropped or widened.
    assert owner.get(f"{API}/applications").json()["total"] == 2
    assert people["outsider"].get(f"{API}/applications", params={"q": payload}).json()["total"] == 0


def test_input_validation_boundaries(people):
    owner = people["owner"]
    assert owner.post(f"{API}/applications", json={"title": "ab", "application_type": "kyc"}).status_code == 422
    assert owner.post(f"{API}/applications", json={"title": "x" * 201, "application_type": "kyc"}).status_code == 422
    assert owner.post(f"{API}/applications", json={"title": 42, "application_type": ["kyc"]}).status_code == 422
    assert (
        owner.post(
            f"{API}/applications", content=b"{not json", headers={"Content-Type": "application/json"}
        ).status_code
        == 422
    )
    for params in ({"limit": 0}, {"limit": 10_000}, {"offset": -1}, {"q": "x" * 101}, {"status": "nonsense"}):
        assert owner.get(f"{API}/applications", params=params).status_code == 422, params
    r = owner.post(f"{API}/applications", json={"title": "  <script>alert(1)</script>  ", "application_type": "kyc"})
    assert (
        r.status_code == 201 and r.json()["title"] == "<script>alert(1)</script>"
    )  # stored as text, escaped by the UI


def test_invalid_rule_definitions_are_rejected_before_storage(people):
    admin = people["manager"]
    ok = {"condition": {"field": "extracted.full_name", "op": "exists"}, "severity": "high"}
    assert admin.post(f"{API}/rules/validate", json={"definition": ok}).json()["valid"] is True
    bad = [  # each differs from the valid definition in one way only
        {**ok, "condition": {"field": "extracted.nonexistent_field", "op": "eq", "value": "x"}},
        {**ok, "condition": {"field": "extracted.full_name", "op": "__import__('os').system", "value": "x"}},
        {**ok, "condition": {"field": "extracted.date_of_birth", "op": "age_years_at_least", "value": "eighteen"}},
        {**ok, "condition": {"all": []}},
        {**ok, "severity": "apocalyptic"},
        {**ok, "condition": "1 == 1"},
        {**ok, "on_violation": "delete_everything"},
    ]
    for definition in bad:
        check = admin.post(f"{API}/rules/validate", json={"definition": definition}).json()
        assert check["valid"] is False and check["errors"], definition
        r = admin.post(
            f"{API}/rules",
            json={
                "key": "bad_rule",
                "name": "Bad rule",
                "category": "eligibility",
                "effective_from": "2026-01-01",
                "definition": definition,
            },
        )
        assert r.status_code == 422, definition
    assert admin.get(f"{API}/rules").json()["items"] == []


# ------------------------------------------------------------------ cross-user leakage


def test_no_endpoint_leaks_another_users_application(people):
    owner, outsider = people["owner"], people["outsider"]
    _publish_adult_rule(people)
    app = _app(owner)
    doc = _upload(owner, app["id"], "private.pdf").json()
    run = owner.post(f"{API}/applications/{app['id']}/validation-runs", json={"evaluation_date": ON}).json()
    assert owner.post(f"{API}/applications/{app['id']}/evidence/analyses", json={"force": False}).status_code in (
        200,
        201,
    )
    a, d = app["id"], doc["id"]
    for path in (
        f"/applications/{a}",
        f"/applications/{a}/documents",
        f"/applications/{a}/documents/{d}",
        f"/applications/{a}/documents/{d}/download",
        f"/applications/{a}/documents/{d}/extraction",
        f"/applications/{a}/documents/{d}/pages/1/image",
        f"/applications/{a}/documents/{d}/verifications",
        f"/applications/{a}/evidence",
        f"/applications/{a}/validation-runs",
        f"/applications/{a}/validation-runs/{run['id']}",
        f"/applications/{a}/validation-runs/{run['id']}/reproduction",
    ):
        r = outsider.get(API + path)
        assert r.status_code == 404, (path, r.status_code)
        assert "private.pdf" not in r.text and "Test Person Alpha" not in r.text
    for path, body in (
        (f"/applications/{a}/documents/{d}/verifications", None),
        (f"/applications/{a}/validation-runs", {"evaluation_date": ON}),
        (f"/applications/{a}/evidence/analyses", {"force": True}),
    ):
        assert outsider.post(API + path, json=body).status_code == 404, path
    assert outsider.get(f"{API}/applications").json()["total"] == 0
    assert outsider.get(f"{API}/reviews").json()["total"] == 0
    assert outsider.get(f"{API}/trust/documents").json()["total"] == 0
    assert outsider.get(f"{API}/insights/overview").json()["scope"]["applications"] == 0
    assert outsider.get(f"{API}/audit/events").status_code == 403
    assert outsider.post(f"{API}/exports", json={"dataset": "audit_events", "format": "csv"}).status_code == 403


# ------------------------------------------------------------------ incorrect source references


def test_corrections_must_reference_the_items_own_document_and_field(people, session_factory):
    owner = people["owner"]
    _publish_adult_rule(people)
    app = _app(owner)
    _upload(
        owner,
        app["id"],
        "minor.pdf",
        factories.labelled_pdf([["Full name: Test Person Alpha", "Date of birth: 01 January 2015"]]),
    )
    owner.post(f"{API}/applications/{app['id']}/validation-runs", json={"evaluation_date": ON})
    item = owner.get(f"{API}/reviews").json()["items"][0]["item"]
    detail = owner.get(f"{API}/reviews/{item['id']}").json()
    field = next(f for f in detail["fields"] if f["field_key"] == "date_of_birth")

    other = _app(owner, "A different synthetic case")
    other_doc = _upload(owner, other["id"], "other.pdf").json()
    other_field = next(
        f
        for f in owner.get(f"{API}/applications/{other['id']}/documents/{other_doc['id']}/extraction").json()["fields"]
        if f["field_key"] == "date_of_birth"
    )

    def correct(document_id: str, field_id: str):  # noqa: ANN202
        return owner.post(
            f"{API}/reviews/{item['id']}/corrections",
            json={
                "expected_version": item["version"],
                "document_id": document_id,
                "field_id": field_id,
                "value": "1990-03-03",
                "reason": "Synthetic source reference check",
            },
        )

    for document_id, field_id in (
        (other_doc["id"], other_field["id"]),  # a field from another application
        (field["document_id"], other_field["id"]),  # a field that is not on this document
        (field["document_id"], "0" * 32),  # a field that does not exist
        ("0" * 32, field["field_id"] if "field_id" in field else field["id"]),
    ):
        r = correct(document_id, field_id)
        assert r.status_code in (404, 409, 422), (document_id, field_id, r.text)
    with session_factory() as s:
        assert s.execute(select(func.count()).select_from(FieldCorrection)).scalar_one() == 0


# ------------------------------------------------------------------ concurrency and duplicates


def test_concurrent_duplicate_uploads_store_one_document(people, session_factory, storage):
    owner = people["owner"]
    app = _app(owner)
    content = factories.labelled_pdf([["Full name: Test Person Alpha", "Date of birth: 03 March 1990"]])
    statuses: list[int] = []
    barrier = threading.Barrier(4)

    def go(i: int) -> None:
        barrier.wait()
        statuses.append(_upload(owner, app["id"], f"copy-{i}.pdf", content).status_code)

    threads = [threading.Thread(target=go, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(statuses).count(201) == 1 and all(s in (201, 409) for s in statuses), statuses
    with session_factory() as s:
        assert s.execute(select(func.count()).select_from(Document)).scalar_one() == 1
    assert len([p for p in Path(storage.root).rglob("*") if p.is_file()]) == 1


def test_concurrent_validation_runs_are_each_complete(people):
    owner = people["owner"]
    _publish_adult_rule(people)
    app = _app(owner)
    _upload(owner, app["id"], "adult.pdf")
    statuses: list[int] = []
    barrier = threading.Barrier(3)

    def go() -> None:
        barrier.wait()
        statuses.append(
            owner.post(f"{API}/applications/{app['id']}/validation-runs", json={"evaluation_date": ON}).status_code
        )

    threads = [threading.Thread(target=go) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert statuses == [201, 201, 201]
    runs = owner.get(f"{API}/applications/{app['id']}/validation-runs").json()
    assert len(runs) == 3 and all(r["summary"]["pass"] == 1 for r in runs)


# ------------------------------------------------------------------ audit tampering through the API


def test_the_api_offers_no_way_to_change_audit_history(people, session_factory):
    admin = people["admin"]
    event = admin.get(f"{API}/audit/events", params={"limit": 1}).json()["items"][0]
    for method in ("put", "patch", "delete"):
        r = getattr(admin, method)(f"{API}/audit/events/{event['id']}")
        assert r.status_code in (404, 405), method
        r = getattr(admin, method)(f"{API}/audit/events")
        assert r.status_code in (404, 405), method
    assert admin.post(f"{API}/audit/events", json={"action": "auth.login", "summary": "forged"}).status_code in (
        404,
        405,
    )
    with session_factory() as s:
        assert (
            s.execute(select(func.count()).select_from(AuditEvent).where(AuditEvent.summary == "forged")).scalar_one()
            == 0
        )
    assert admin.get(f"{API}/audit/verify").json()["valid"] is True


# ------------------------------------------------------------------ migrations


def test_migrations_from_an_empty_database_match_the_models_and_round_trip(tmp_path):
    db = tmp_path / "fresh.db"
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.attributes["database_url"] = f"sqlite:///{db.as_posix()}"
    command.upgrade(cfg, "head")
    engine = create_engine(f"sqlite:///{db.as_posix()}")

    def diff() -> list:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn, opts={"compare_type": False})
            return compare_metadata(ctx, Base.metadata)

    assert diff() == []
    command.downgrade(cfg, "base")
    with engine.connect() as conn:
        tables = set(conn.dialect.get_table_names(conn)) - {"alembic_version"}
    assert tables == set()
    command.upgrade(cfg, "head")
    assert diff() == []
    engine.dispose()
