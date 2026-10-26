"""Trust Center API: verification runs, honest states, altered files, history by hash, authorization."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from sqlalchemy import select, text

from app.core.config import Settings, get_settings
from app.core.roles import Role
from app.models import AuditEvent, Document, TrustVerification
from app.models.trust import ImmutableVerificationError
from app.trust.synthetic_pki import SyntheticPKI, unsigned_pdf
from tests import factories

API = "/api/v1"
LINES = ["Full name: Test Person Alpha", "Date of birth: 03 March 1990", "Document number: SYN-000123"]


@pytest.fixture(scope="module")
def pki() -> SyntheticPKI:
    return SyntheticPKI.create()


@pytest.fixture
def trust_config(monkeypatch, tmp_path, pki):
    """Configure a synthetic trust anchor and the synthetic registry for one test."""
    roots = tmp_path / "roots"
    roots.mkdir()
    (roots / "synthetic-root.pem").write_bytes(pki.root.pem())

    def apply(**env: str) -> None:
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        get_settings.cache_clear()

    apply(VERIFYFLOW_TRUST_ROOTS_DIR=str(roots), VERIFYFLOW_REGISTRY_CONNECTORS=json.dumps(["synthetic"]))
    yield apply
    get_settings.cache_clear()


@pytest.fixture
def people(make_user, login):
    make_user(Role.REVIEWER, email="owner@example.org")
    make_user(Role.REVIEWER, email="outsider@example.org")
    make_user(Role.AUDITOR, email="auditor@example.org")
    return {n: login(f"{n}@example.org") for n in ("owner", "outsider", "auditor")}


def upload(c, app_id, name, data, mime="application/pdf"):  # noqa: ANN001, ANN201
    r = c.post(f"{API}/applications/{app_id}/documents", files={"file": (name, data, mime)})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def app_id(people):
    return (
        people["owner"]
        .post(f"{API}/applications", json={"title": "Trust case", "application_type": "kyc"})
        .json()["id"]
    )


def verify(c, app_id, doc_id):  # noqa: ANN001, ANN201
    return c.post(f"{API}/applications/{app_id}/documents/{doc_id}/verifications")


def by_dim(run: dict) -> dict:
    return {c["dimension"]: c for c in run["checks"]}


def test_signed_document_full_verification(people, app_id, pki, trust_config):
    doc = upload(people["owner"], app_id, "signed.pdf", pki.sign(unsigned_pdf(LINES)))
    r = verify(people["owner"], app_id, doc["id"])
    assert r.status_code == 201, r.text
    run = r.json()
    assert run["recorded_sha256"] == run["observed_sha256"] == doc["sha256"]
    assert run["summary"] == {
        "file_integrity": "verified",
        "signature_integrity": "verified",
        "certificate_trust": "verified",
        "revocation": "unsupported",
        "timestamp": "inconclusive",
        "external_registry": "verified",
    }
    d = by_dim(run)
    assert "who created or issued the document" in d["file_integrity"]["does_not_establish"]
    assert "that the document's contents are true" in d["signature_integrity"]["does_not_establish"]
    assert any("SYNTHETIC" in lim for lim in d["external_registry"]["limitations"])
    assert run["config"]["trust_anchors"][0]["subject"].endswith("SYNTHETIC TEST ROOT")
    assert run["signatures"][0]["field_name"] == "Signature1"
    assert "pyHanko/" in run["engine_version"]


def test_unsigned_and_image_documents_are_never_verified_for_signatures(people, app_id, trust_config):
    trust_config(VERIFYFLOW_REGISTRY_CONNECTORS="[]")
    pdf = upload(people["owner"], app_id, "plain.pdf", factories.labelled_pdf([LINES]))
    png = upload(people["owner"], app_id, "scan.png", factories.png(), "image/png")
    a = verify(people["owner"], app_id, pdf["id"]).json()
    b = verify(people["owner"], app_id, png["id"]).json()
    assert a["summary"] == {
        "file_integrity": "verified",
        "signature_integrity": "inconclusive",
        "external_registry": "unsupported",
    }
    assert b["summary"]["signature_integrity"] == "unsupported"
    assert by_dim(b)["signature_integrity"]["code"] == "not_pdf"
    assert by_dim(a)["external_registry"]["code"] == "no_registry_configured"


def test_altered_stored_file_fails_integrity_and_skips_signature_inspection(
    people, app_id, pki, trust_config, storage, session_factory
):
    doc = upload(people["owner"], app_id, "signed.pdf", pki.sign(unsigned_pdf(LINES)))
    with session_factory() as s:
        key = s.get(Document, doc["id"]).storage_key
    path = storage.path(key)
    data = bytearray(path.read_bytes())
    data[-10] ^= 0x01
    path.write_bytes(bytes(data))
    run = verify(people["owner"], app_id, doc["id"]).json()
    d = by_dim(run)
    assert (d["file_integrity"]["state"], d["file_integrity"]["code"]) == ("failed", "hash_mismatch")
    assert run["observed_sha256"] != run["recorded_sha256"] == doc["sha256"]
    assert (d["signature_integrity"]["state"], d["signature_integrity"]["code"]) == (
        "inconclusive",
        "stored_file_not_verified",
    )
    path.unlink()
    gone = by_dim(verify(people["owner"], app_id, doc["id"]).json())
    assert (gone["file_integrity"]["state"], gone["file_integrity"]["code"]) == ("failed", "file_missing")


def test_document_altered_after_signing_fails_signature_but_hash_matches_upload(people, app_id, pki, trust_config):
    """The uploaded file is intact in storage, yet its signature shows it was changed after signing."""
    from app.trust.synthetic_pki import append_unpermitted_update

    tampered = append_unpermitted_update(pki.sign(unsigned_pdf(LINES)))
    doc = upload(people["owner"], app_id, "tampered.pdf", tampered)
    s = verify(people["owner"], app_id, doc["id"]).json()["summary"]
    assert s["file_integrity"] == "verified" and s["signature_integrity"] == "failed"


def test_untrusted_signer_and_unavailable_registry(people, app_id, trust_config):
    trust_config(
        VERIFYFLOW_REGISTRY_CONNECTORS=json.dumps(["http_json"]),
        VERIFYFLOW_REGISTRY_HTTP_URL="http://127.0.0.1:9/registry",
        VERIFYFLOW_REGISTRY_HTTP_TIMEOUT_SECONDS="1",
    )
    from app.trust.synthetic_pki import issue

    other_root = issue("Unrelated Synthetic Root", ca=True)
    stranger = SyntheticPKI(root=other_root, signer=issue("Stranger Signer", other_root))
    doc = upload(people["owner"], app_id, "stranger.pdf", stranger.sign(unsigned_pdf(LINES)))
    d = by_dim(verify(people["owner"], app_id, doc["id"]).json())
    assert (d["certificate_trust"]["state"], d["certificate_trust"]["code"]) == ("inconclusive", "untrusted_chain")
    assert d["signature_integrity"]["state"] == "verified"
    assert (d["external_registry"]["state"], d["external_registry"]["code"]) == ("inconclusive", "registry_unavailable")
    # An impostor root with the trusted root's *name* but a different key: never trusted.
    impostor = SyntheticPKI.create()
    doc2 = upload(people["owner"], app_id, "impostor.pdf", impostor.sign(unsigned_pdf(LINES)))
    d2 = by_dim(verify(people["owner"], app_id, doc2["id"]).json())
    assert (d2["certificate_trust"]["state"], d2["certificate_trust"]["code"]) == (
        "inconclusive",
        "chain_validation_error",
    )


def test_history_is_immutable_and_linked_by_hash(people, app_id, pki, trust_config, session_factory):
    owner = people["owner"]
    data = pki.sign(unsigned_pdf(LINES))
    doc = upload(owner, app_id, "signed.pdf", data)
    first = verify(owner, app_id, doc["id"]).json()
    second = verify(owner, app_id, doc["id"]).json()
    other_app = owner.post(f"{API}/applications", json={"title": "Second case", "application_type": "kyc"}).json()["id"]
    copy = upload(owner, other_app, "same-file.pdf", data)
    h = owner.get(f"{API}/applications/{app_id}/documents/{doc['id']}/verifications").json()
    assert [v["id"] for v in h["verifications"]] == [second["id"], first["id"]]
    assert all(v["recorded_sha256"] == doc["sha256"] for v in h["verifications"])
    assert h["same_hash_documents"] == [
        {
            "document_id": copy["id"],
            "application_id": other_app,
            "reference": h["same_hash_documents"][0]["reference"],
            "filename": "same-file.pdf",
        }
    ]
    assert h["can_verify"] is True
    got = owner.get(f"{API}/applications/{app_id}/documents/{doc['id']}/verifications/{first['id']}").json()
    assert got["checks"] == first["checks"]
    with session_factory() as s:
        v = s.get(TrustVerification, first["id"])
        v.summary = {"file_integrity": "verified"}
        with pytest.raises(ImmutableVerificationError):
            s.flush()
        s.rollback()
        with pytest.raises(Exception, match="append-only"):
            s.execute(text("UPDATE trust_verifications SET summary = '{}'"))
        s.rollback()
        with pytest.raises(Exception, match="append-only"):
            s.execute(text("DELETE FROM trust_verifications"))
        s.rollback()
        events = s.execute(select(AuditEvent).where(AuditEvent.action == "trust.verified")).scalars().all()
        assert len(events) == 2 and events[0].data["recorded_sha256"] == doc["sha256"]


def test_authorization(people, app_id, pki, trust_config):
    owner = people["owner"]
    doc = upload(owner, app_id, "signed.pdf", pki.sign(unsigned_pdf(LINES)))
    url = f"{API}/applications/{app_id}/documents/{doc['id']}/verifications"
    assert people["outsider"].post(url).status_code == 404
    assert people["outsider"].get(url).status_code == 404
    assert people["outsider"].get(f"{API}/trust/documents").json()["total"] == 0
    assert people["auditor"].post(url).status_code == 403
    assert people["auditor"].get(url).json()["can_verify"] is False
    owner.post(f"{API}/applications/{app_id}/members", json={"email": "outsider@example.org", "role": "viewer"})
    assert people["outsider"].post(url).status_code == 403  # viewers can read but not verify
    assert people["outsider"].get(url).status_code == 200
    owner.post(f"{API}/applications/{app_id}/transitions", json={"action": "archive", "reason": "closing case"})
    assert verify(owner, app_id, doc["id"]).status_code == 409
    other = owner.post(f"{API}/applications", json={"title": "Other", "application_type": "kyc"}).json()["id"]
    assert owner.get(f"{API}/applications/{other}/documents/{doc['id']}/verifications").status_code == 404


def test_overview_and_capabilities(people, app_id, pki, trust_config):
    owner = people["owner"]
    doc = upload(owner, app_id, "signed.pdf", pki.sign(unsigned_pdf(LINES)))
    upload(owner, app_id, "plain.pdf", factories.labelled_pdf([["Full name: Test Person Alpha"]]))
    verify(owner, app_id, doc["id"])
    o = owner.get(f"{API}/trust/documents").json()
    latest = {row["document"]["original_filename"]: row["latest"] for row in o["items"]}
    assert latest["plain.pdf"] is None and latest["signed.pdf"]["summary"]["signature_integrity"] == "verified"
    caps = {c["key"]: c for c in owner.get(f"{API}/trust/capabilities").json()["capabilities"]}
    assert caps["certificate_trust"]["status"] == "enabled" and caps["revocation_online"]["status"] == "disabled"
    assert caps["ltv"]["status"] == "not_implemented" and caps["registry"]["status"] == "enabled"
    trust_config(VERIFYFLOW_TRUST_ROOTS_DIR="", VERIFYFLOW_REGISTRY_CONNECTORS="[]")
    caps = {c["key"]: c for c in owner.get(f"{API}/trust/capabilities").json()["capabilities"]}
    assert caps["certificate_trust"]["status"] == "not_configured" and caps["registry"]["status"] == "not_configured"


@pytest.mark.parametrize(
    "env,msg",
    [
        ({"registry_connectors": ["synthetic"]}, "development and tests only"),
        ({"registry_http_url": "http://registry.example.test/x"}, "https://"),
    ],
)
def test_production_refuses_unsafe_trust_settings(env, msg):
    base = {
        "environment": "production",
        "database_url": "postgresql://u@h/db",
        "cors_origins": ["https://app.example.test"],
        "cookie_secure": True,
    }
    with pytest.raises(ValidationError, match=msg):
        Settings(**base, **env)


def test_unknown_connector_rejected():
    with pytest.raises(ValidationError, match="unknown registry connector"):
        Settings(registry_connectors=["made_up"])


def test_system_capability_reflects_configured_trust_anchors(people, trust_config):
    """The status card on the Command Center must match the real Trust Center configuration."""
    caps = {c["key"]: c for c in people["owner"].get(f"{API}/system/capabilities").json()["capabilities"]}
    sig = caps["digital_signature_validation"]
    assert sig["available"] is True and "1 trust anchor" in sig["detail"] and "synthetic" in sig["detail"]
    trust_config(VERIFYFLOW_TRUST_ROOTS_DIR="")
    caps = {c["key"]: c for c in people["owner"].get(f"{API}/system/capabilities").json()["capabilities"]}
    assert caps["digital_signature_validation"]["available"] is False
