"""Signature inspection, revocation, timestamps and registries against synthetic PKI fixtures."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.trust import anchors, registries, signatures
from app.trust.checks import State, summarize
from app.trust.synthetic_pki import SyntheticPKI, append_unpermitted_update, crl, flip_signed_byte, issue, unsigned_pdf
from tests import factories


@pytest.fixture(scope="module")
def pki() -> SyntheticPKI:
    return SyntheticPKI.create(with_tsa=True)


@pytest.fixture(scope="module")
def signed(pki) -> bytes:
    return pki.sign(unsigned_pdf())


def run(data: bytes, roots=(), crls=(), fetching=False, mime="application/pdf"):  # noqa: ANN001, ANN201
    material = anchors.TrustMaterial(roots=list(roots), crls=list(crls))
    checks, details = signatures.inspect(data, mime, signatures.Options(material, fetching))
    by_dim = {c.dimension.value: c for c in checks}
    return by_dim, details, [c.to_dict() for c in checks]


# ------------------------------------------------------------------ unsigned, unsupported, malformed


def test_unsigned_pdf_is_inconclusive_not_failed():
    by, details, _ = run(unsigned_pdf())
    c = by["signature_integrity"]
    assert (c.state, c.code) == (State.INCONCLUSIVE, "no_signature")
    assert "not evidence of forgery" in c.summary and details == []
    assert set(by) == {"signature_integrity"}


@pytest.mark.parametrize("data,mime", [(factories.png(), "image/png"), (factories.jpeg(), "image/jpeg")])
def test_non_pdf_is_unsupported(data, mime):
    by, _, _ = run(data, mime=mime)
    assert (by["signature_integrity"].state, by["signature_integrity"].code) == (State.UNSUPPORTED, "not_pdf")


def test_unreadable_pdf_is_unsupported():
    by, _, _ = run(b"%PDF-1.7\n this is not a real pdf \n%%EOF")
    assert by["signature_integrity"].state == State.UNSUPPORTED


def test_damaged_signature_value_fails(signed):
    data = bytearray(signed)
    start = data.index(b"/Contents <") + len(b"/Contents <")
    end = data.index(b">", start)
    used = len(bytes(data[start:end]).rstrip(b"0"))  # the CMS blob is zero-padded to the reserved size
    i = start + used - 16  # the signature value is the last element of the SignerInfo
    data[i : i + 8] = b"0123ABCD" if data[i : i + 8] != b"0123ABCD" else b"89EFCDAB"
    by, _, _ = run(bytes(data))
    assert by["signature_integrity"].state == State.FAILED
    assert by["signature_integrity"].code in ("invalid_signature", "malformed_signature")


# ------------------------------------------------------------------ integrity


def test_trusted_signature_is_verified_and_scoped(pki, signed):
    by, details, _ = run(signed, roots=[pki.root.asn1])
    integ, trust = by["signature_integrity"], by["certificate_trust"]
    assert (integ.state, integ.code) == (State.VERIFIED, "intact_entire_file")
    assert (trust.state, trust.code) == (State.VERIFIED, "chain_to_configured_anchor")
    assert "that the document's contents are true" in integ.does_not_establish
    assert "SYNTHETIC TEST ROOT" in trust.evidence["chain"][0] and "Synthetic Signer" in trust.evidence["chain"][-1]
    assert "SYNTHETIC TEST ROOT" in trust.summary
    assert "Synthetic Signer (Test Person Alpha)" in details[0]["signer"]["subject"]
    assert details[0]["digest_algorithm"] == "sha256" and details[0]["coverage"] == "ENTIRE_FILE"
    # Revocation isn't configured: honestly unsupported. No timestamp: signing time is self-reported.
    assert (by["revocation"].state, by["revocation"].code) == (State.UNSUPPORTED, "revocation_not_configured")
    assert (by["timestamp"].state, by["timestamp"].code) == (State.INCONCLUSIVE, "no_timestamp")


def test_altered_signed_bytes_fail(pki, signed):
    by, _, _ = run(flip_signed_byte(signed), roots=[pki.root.asn1])
    assert (by["signature_integrity"].state, by["signature_integrity"].code) == (State.FAILED, "digest_mismatch")


def test_unpermitted_change_after_signing_fails(pki, signed):
    by, details, _ = run(append_unpermitted_update(signed), roots=[pki.root.asn1])
    c = by["signature_integrity"]
    assert (c.state, c.code) == (State.FAILED, "modified_after_signing")
    assert details[0]["coverage"] == "ENTIRE_REVISION" and details[0]["modification_level"] == "OTHER"


def test_multiple_signatures_are_each_checked(pki, signed):
    second = pki.sign(signed, field_name="Signature2")
    _, details, dicts = run(second, roots=[pki.root.asn1])
    assert [d["field_name"] for d in details] == ["Signature1", "Signature2"]
    integ = [c for c in dicts if c["dimension"] == "signature_integrity"]
    assert [(c["subject"], c["state"]) for c in integ] == [("Signature1", "verified"), ("Signature2", "verified")]
    assert integ[0]["code"] == "intact_permitted_updates"  # a later signature is a permitted update


# ------------------------------------------------------------------ certificate trust


def test_no_anchors_configured_is_inconclusive(signed):
    by, _, _ = run(signed)
    assert (by["certificate_trust"].state, by["certificate_trust"].code) == (
        State.INCONCLUSIVE,
        "no_trust_anchors_configured",
    )
    # A valid signature is still reported as intact: integrity and trust are separate questions.
    assert by["signature_integrity"].state == State.VERIFIED


def test_untrusted_issuer_is_inconclusive(signed):
    other = issue("Unrelated Root", ca=True)
    by, _, _ = run(signed, roots=[other.asn1])
    assert (by["certificate_trust"].state, by["certificate_trust"].code) == (State.INCONCLUSIVE, "untrusted_chain")


def test_self_signed_signer_is_not_trusted(pki):
    rogue = issue("Self-signed Rogue Signer")
    data = SyntheticPKI(root=rogue, signer=rogue).sign(unsigned_pdf())
    by, details, _ = run(data, roots=[pki.root.asn1])
    assert by["signature_integrity"].state == State.VERIFIED  # mathematically fine…
    assert by["certificate_trust"].state == State.INCONCLUSIVE  # …but the identity is unconfirmed
    assert details[0]["signer"]["self_signed"] is True


def test_expired_certificate_is_inconclusive(pki):
    now = datetime.now(UTC)
    expired = issue("Expired Signer", pki.root, not_before=now - timedelta(days=30), not_after=now - timedelta(days=5))
    by, _, _ = run(pki.sign(unsigned_pdf(), signer=expired), roots=[pki.root.asn1])
    assert (by["certificate_trust"].state, by["certificate_trust"].code) == (
        State.INCONCLUSIVE,
        "certificate_outside_validity",
    )


# ------------------------------------------------------------------ revocation


def test_offline_crl_revoked_and_clean(pki, signed):
    clean, _, _ = run(signed, roots=[pki.root.asn1], crls=[_crl(pki, [])])
    assert (clean["revocation"].state, clean["revocation"].code) == (State.VERIFIED, "not_revoked")
    revoked, _, _ = run(signed, roots=[pki.root.asn1], crls=[_crl(pki, [pki.signer.cert])])
    r = revoked["revocation"]
    assert (r.state, r.code) == (State.FAILED, "revoked") and r.evidence["revocation_date"]
    # Trust (chain building) is reported separately from revocation.
    assert revoked["certificate_trust"].state == State.VERIFIED


def test_unrelated_crl_is_inconclusive_not_verified(pki, signed):
    other = issue("Other CA", ca=True)
    by, _, _ = run(signed, roots=[pki.root.asn1], crls=[crl(other)])
    assert (by["revocation"].state, by["revocation"].code) == (State.INCONCLUSIVE, "revocation_unavailable")


def test_unreachable_revocation_service_is_inconclusive():
    p = SyntheticPKI.create(crl_url="http://127.0.0.1:9/synthetic.crl")  # nothing listens on the discard port
    by, _, _ = run(p.sign(unsigned_pdf()), roots=[p.root.asn1], fetching=True)
    assert (by["revocation"].state, by["revocation"].code) == (State.INCONCLUSIVE, "revocation_unavailable")
    assert by["certificate_trust"].state == State.VERIFIED


def test_revocation_needs_a_trusted_chain(signed):
    by, _, _ = run(signed, crls=[])
    assert (by["revocation"].state, by["revocation"].code) == (State.INCONCLUSIVE, "no_trusted_chain")


def _crl(pki: SyntheticPKI, revoked: list):  # noqa: ANN202
    from asn1crypto import crl as a_crl

    return a_crl.CertificateList.load(crl(pki.root, revoked))


# ------------------------------------------------------------------ timestamps


def test_trusted_timestamp_is_verified(pki):
    by, details, _ = run(pki.sign(unsigned_pdf(), timestamp=True), roots=[pki.root.asn1])
    t = by["timestamp"]
    assert (t.state, t.code) == (State.VERIFIED, "trusted_timestamp")
    assert "Synthetic Timestamp Authority" in details[0]["timestamp"]["tsa"]


def test_timestamp_from_untrusted_tsa_is_inconclusive(pki):
    other = SyntheticPKI.create(with_tsa=True)
    data = SyntheticPKI(root=other.root, signer=pki.signer, tsa=other.tsa).sign(unsigned_pdf(), timestamp=True)
    by, _, _ = run(data, roots=[pki.root.asn1])
    assert (by["timestamp"].state, by["timestamp"].code) == (State.INCONCLUSIVE, "untrusted_timestamp")


# ------------------------------------------------------------------ aggregation and anchors


def test_summary_never_reports_verified_unless_every_check_is():
    mk = lambda dim, st: {"dimension": dim, "state": st}  # noqa: E731
    assert summarize([mk("signature_integrity", "verified"), mk("signature_integrity", "unsupported")]) == {
        "signature_integrity": "unsupported"
    }
    assert summarize([mk("certificate_trust", "verified"), mk("certificate_trust", "inconclusive")]) == {
        "certificate_trust": "inconclusive"
    }
    assert summarize([mk("revocation", "inconclusive"), mk("revocation", "failed")]) == {"revocation": "failed"}


def test_anchor_loading_reports_bad_files(tmp_path, pki):
    (tmp_path / "root.pem").write_bytes(pki.root.pem())
    (tmp_path / "broken.pem").write_bytes(b"-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n")
    (tmp_path / "notes.txt").write_text("ignored: not a certificate suffix")
    tm = anchors.load(tmp_path, tmp_path / "missing")
    assert len(tm.roots) == 1 and any("broken.pem" in p for p in tm.problems)
    assert any("CRL directory not found" in p for p in tm.problems)
    assert (
        tm.describe()["trust_anchors"][0]["sha256"]
        == pki.root.cert.fingerprint(
            __import__("cryptography.hazmat.primitives.hashes", fromlist=["SHA256"]).SHA256()
        ).hex()
    )


# ------------------------------------------------------------------ registries


SYN = registries.SyntheticRegistry()


@pytest.mark.parametrize(
    "values,state,code",
    [
        (
            {"document_number": "SYN-000123", "full_name": "Test Person Alpha", "date_of_birth": "1990-03-03"},
            State.VERIFIED,
            "registry_match",
        ),
        ({"document_number": "SYN-000123", "full_name": "Test Person Omega"}, State.FAILED, "registry_mismatch"),
        ({"document_number": "SYN-000456", "full_name": "Test Person Beta"}, State.FAILED, "registry_status_revoked"),
        ({"document_number": "SYN-999999", "full_name": "Test Person Alpha"}, State.INCONCLUSIVE, "not_found"),
        ({"full_name": "Test Person Alpha"}, State.UNSUPPORTED, "no_document_number"),
        ({"document_number": "SYN-000789"}, State.INCONCLUSIVE, "nothing_to_compare"),
    ],
)
def test_synthetic_registry_outcomes(values, state, code):
    c = SYN.check(registries.Fields(values))
    assert (c.state, c.code) == (state, code)
    assert any("SYNTHETIC" in lim for lim in c.limitations)
    assert "that this particular file or paper document is genuine" in c.does_not_establish


def test_synthetic_registry_refused_in_production():
    assert (
        registries.configured(
            ["synthetic"], environment="production", synthetic_path=None, http_url=None, http_timeout=1, http_name="x"
        )
        == []
    )


def test_http_registry_unavailable_is_inconclusive():
    reg = registries.HttpJsonRegistry("http://127.0.0.1:9/registry", 1.0, "Test registry")
    c = reg.check(registries.Fields({"document_number": "SYN-000123"}))
    assert (c.state, c.code) == (State.INCONCLUSIVE, "registry_unavailable")


@pytest.mark.parametrize(
    "response,state,code",
    [
        (httpx.Response(503, text="maintenance"), State.INCONCLUSIVE, "registry_error"),
        (httpx.Response(200, text="<html>not json</html>"), State.INCONCLUSIVE, "registry_bad_response"),
        (httpx.Response(200, json={"found": "yes"}), State.INCONCLUSIVE, "registry_bad_response"),
        (httpx.Response(200, json={"found": False}), State.INCONCLUSIVE, "not_found"),
        (
            httpx.Response(200, json={"found": True, "status": "valid", "record": {"full_name": "Test Person Alpha"}}),
            State.VERIFIED,
            "registry_match",
        ),
        (
            httpx.Response(200, json={"found": True, "status": "cancelled", "record": {}}),
            State.FAILED,
            "registry_status_cancelled",
        ),
    ],
)
def test_http_registry_responses(monkeypatch, response, state, code):
    seen = {}

    def fake_get(url, params, timeout, follow_redirects):  # noqa: ANN001, ANN202
        seen.update(url=url, params=params, redirects=follow_redirects)
        return response

    monkeypatch.setattr(registries.httpx, "get", fake_get)
    reg = registries.HttpJsonRegistry("https://registry.example.test/lookup", 2.0, "Test registry")
    c = reg.check(registries.Fields({"document_number": "SYN-000123", "full_name": "Test Person Alpha"}))
    assert (c.state, c.code) == (state, code)
    assert seen == {
        "url": "https://registry.example.test/lookup",
        "params": {"document_number": "SYN-000123"},
        "redirects": False,
    }
