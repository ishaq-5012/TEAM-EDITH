"""Embedded PDF signature inspection with pyHanko.

For each signature, four separate checks are produced:

- signature_integrity: the signed byte range still matches the signature (``intact``), the cryptographic signature
  verifies (``valid``), and later incremental updates are of a kind the signature permits.
- certificate_trust: the signer certificate chains to an anchor configured by this deployment and is within its
  validity period. Never the operating system's TLS trust list.
- revocation: only when offline CRLs are configured or online fetching is explicitly enabled.
- timestamp: an embedded RFC 3161 timestamp token, validated against the same anchors.

Mapping from pyHanko / ETSI AdES indications (documented in docs/API.md):
  AdESFailure.*                         -> failed
  revoked (REVOKED / REVOKED_NO_POE)    -> revocation failed
  NO_CERTIFICATE_CHAIN_FOUND            -> certificate trust inconclusive (no configured anchor matched)
  OUT_OF_BOUNDS_NO_POE / NOT_REVOKED    -> certificate trust inconclusive (outside validity, no proof of time)
  other AdESIndeterminate.*             -> inconclusive
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass

from pyhanko.pdf_utils.misc import PdfError
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign.ades.report import AdESFailure, AdESIndeterminate
from pyhanko.sign.validation import validate_pdf_signature
from pyhanko.sign.validation.errors import SignatureValidationError
from pyhanko.sign.validation.status import SignatureCoverageLevel
from pyhanko_certvalidator import ValidationContext
from pyhanko_certvalidator.errors import PathBuildingError
from pyhanko_certvalidator.policy_decl import REQUIRE_REVINFO, CertRevTrustPolicy

from app.trust.anchors import TrustMaterial
from app.trust.checks import NOT_ESTABLISHED, Check, Dimension, State

log = logging.getLogger("verifyflow.trust")
D, S = Dimension, State
METHOD = "pyHanko embedded signature validation (CMS/PAdES, ISO 32000)"


@dataclass
class Options:
    material: TrustMaterial
    revocation_fetching: bool = False


def _cert_info(cert) -> dict:  # noqa: ANN001
    validity = cert["tbs_certificate"]["validity"]
    return {
        "subject": cert.subject.human_friendly,
        "issuer": cert.issuer.human_friendly,
        "serial_number": format(cert.serial_number, "x"),
        "not_before": validity["not_before"].native.isoformat(),
        "not_after": validity["not_after"].native.isoformat(),
        "sha256_fingerprint": cert.sha256.hex(),
        "self_signed": cert.self_signed in ("yes", "maybe"),
    }


def _indication(st) -> str | None:  # noqa: ANN001
    return st.trust_problem_indic.name if st.trust_problem_indic is not None else None


def _base(dim: Dimension, field_name: str, label: str) -> dict:
    return {
        "dimension": dim,
        "key": f"{dim.value}:{field_name}",
        "label": label,
        "subject": field_name,
        "method": METHOD,
        "does_not_establish": NOT_ESTABLISHED[dim],
    }


def _no_pdf_signatures(state: State, code: str, summary: str, limitations: list[str] | None = None) -> list[Check]:
    return [
        Check(
            dimension=D.SIGNATURE_INTEGRITY,
            key="signature_integrity",
            label="Digital signature",
            state=state,
            code=code,
            method=METHOD,
            summary=summary,
            does_not_establish=NOT_ESTABLISHED[D.SIGNATURE_INTEGRITY],
            limitations=limitations or [],
        )
    ]


def inspect(data: bytes, mime: str, opts: Options) -> tuple[list[Check], list[dict]]:
    """Return (checks, per-signature details). Never raises for malformed input: it reports instead."""
    if mime != "application/pdf":
        return _no_pdf_signatures(
            S.UNSUPPORTED,
            "not_pdf",
            "Digital-signature inspection is implemented for PDF only. This file type cannot carry a PDF signature, "
            "and other signature formats (for example detached CMS or XML signatures) are not supported.",
        ), []
    try:
        reader = PdfFileReader(io.BytesIO(data), strict=False)
        if reader.encrypted:
            return _no_pdf_signatures(
                S.UNSUPPORTED,
                "encrypted_pdf",
                "The PDF is encrypted; its signatures can't be inspected without the password, which VerifyFlow "
                "never asks for.",
            ), []
        embedded = list(reader.embedded_signatures)
    except (PdfError, ValueError, KeyError, TypeError) as exc:
        return _no_pdf_signatures(
            S.UNSUPPORTED,
            "unreadable_pdf",
            f"The PDF structure could not be read for signature inspection ({exc.__class__.__name__}).",
        ), []
    if not embedded:
        return _no_pdf_signatures(
            S.INCONCLUSIVE,
            "no_signature",
            "The document carries no embedded digital signature, so its origin can't be established "
            "cryptographically. This is not evidence of forgery: many genuine documents are unsigned.",
        ), []
    checks: list[Check] = []
    details: list[dict] = []
    for sig in embedded:
        c, d = _inspect_one(sig, opts)
        checks += c
        details.append(d)
    return checks, details


def _validate(sig, roots, **kw):  # noqa: ANN001, ANN202
    vc = ValidationContext(trust_roots=list(roots), **kw)
    return validate_pdf_signature(sig, vc)


def _inspect_one(sig, opts: Options) -> tuple[list[Check], dict]:  # noqa: ANN001, C901, PLR0912, PLR0915
    field_name = sig.field_name or "unnamed"
    roots = opts.material.roots
    sub_filter = str(sig.sig_object.get("/SubFilter", "")) or None
    try:
        st = _validate(sig, roots, allow_fetching=False, revocation_mode="soft-fail")
    except (SignatureValidationError, PdfError, ValueError, KeyError, TypeError) as exc:
        detail = {"field_name": field_name, "sub_filter": sub_filter, "error": exc.__class__.__name__}
        return [
            Check(
                **_base(D.SIGNATURE_INTEGRITY, field_name, f"Signature “{field_name}”"),
                state=S.FAILED,
                code="malformed_signature",
                summary=f"The signature data could not be validated ({exc.__class__.__name__}); it is damaged "
                "or not a valid CMS signature.",
                evidence=detail,
            )
        ], detail
    except NotImplementedError as exc:
        detail = {"field_name": field_name, "sub_filter": sub_filter, "error": str(exc)[:200]}
        return [
            Check(
                **_base(D.SIGNATURE_INTEGRITY, field_name, f"Signature “{field_name}”"),
                state=S.UNSUPPORTED,
                code="unsupported_signature_format",
                summary=f"This signature format ({sub_filter or 'unknown'}) is not supported by the validator.",
                evidence=detail,
            )
        ], detail

    signer = _cert_info(st.signing_cert)
    coverage = st.coverage.name if st.coverage is not None else None
    modification = st.modification_level.name if st.modification_level is not None else None
    detail = {
        "field_name": field_name,
        "sub_filter": sub_filter,
        "signer": signer,
        "digest_algorithm": st.md_algorithm,
        "signer_reported_time": st.signer_reported_dt.isoformat() if st.signer_reported_dt else None,
        "coverage": coverage,
        "modification_level": modification,
        "docmdp_ok": st.docmdp_ok,
        "intact": st.intact,
        "cryptographically_valid": st.valid,
        "validation_time": st.validation_time.isoformat() if st.validation_time else None,
    }
    checks: list[Check] = []

    # ---- signature integrity
    base = _base(D.SIGNATURE_INTEGRITY, field_name, f"Signature “{field_name}”")
    evidence = {
        k: detail[k]
        for k in (
            "digest_algorithm",
            "coverage",
            "modification_level",
            "intact",
            "cryptographically_valid",
            "sub_filter",
        )
    }
    evidence["signer"] = signer["subject"]
    establishes = (
        "The bytes covered by this signature are exactly the bytes that were signed, and the signature was "
        "made with the private key matching the signer certificate."
    )
    if not st.intact:
        checks.append(
            Check(
                **base,
                state=S.FAILED,
                code="digest_mismatch",
                evidence=evidence,
                summary="The signed content was changed after signing: its digest no longer matches.",
            )
        )
    elif not st.valid:
        checks.append(
            Check(
                **base,
                state=S.FAILED,
                code="invalid_signature",
                evidence=evidence,
                summary="The cryptographic signature does not verify against the signer's public key.",
            )
        )
    elif st.coverage == SignatureCoverageLevel.ENTIRE_FILE:
        checks.append(
            Check(
                **base,
                state=S.VERIFIED,
                code="intact_entire_file",
                evidence=evidence,
                establishes=establishes,
                summary="The signature is intact and covers the entire file.",
            )
        )
    elif st.coverage == SignatureCoverageLevel.ENTIRE_REVISION:
        if st.docmdp_ok is False or modification == "OTHER":
            checks.append(
                Check(
                    **base,
                    state=S.FAILED,
                    code="modified_after_signing",
                    evidence=evidence,
                    summary="The signed revision is intact, but the file was changed afterwards in a way "
                    "the signature does not permit. The current content is not what was signed.",
                )
            )
        else:
            checks.append(
                Check(
                    **base,
                    state=S.VERIFIED,
                    code="intact_permitted_updates",
                    evidence=evidence,
                    establishes=establishes,
                    limitations=[
                        "Later incremental updates exist; they were classified as permitted "
                        f"({modification or 'unknown'}), e.g. form filling or further signatures."
                    ],
                    summary="The signature is intact; later updates are of a kind it permits.",
                )
            )
    else:
        checks.append(
            Check(
                **base,
                state=S.INCONCLUSIVE,
                code="unclear_coverage",
                evidence=evidence,
                summary="The signature's byte range does not clearly cover the document, so what it "
                "protects is uncertain.",
            )
        )

    # ---- certificate trust (no revocation here: that is a separate check)
    base = _base(D.CERTIFICATE_TRUST, field_name, f"Signer certificate of “{field_name}”")
    indic = _indication(st)
    chain = (
        [c.subject.human_friendly for c in st.validation_path.iter_certs(include_root=True)]
        if (st.validation_path is not None)
        else []
    )
    t_evidence = {"signer": signer, "trust_anchors_configured": len(roots), "indication": indic, "chain": chain}
    trusted = st.trusted
    if trusted:
        checks.append(
            Check(
                **base,
                state=S.VERIFIED,
                code="chain_to_configured_anchor",
                evidence=t_evidence,
                establishes="The signer certificate chains to a trust anchor configured by this "
                "deployment and was within its validity period at validation time.",
                limitations=["Trust is only as strong as the configured anchors."],
                summary=f"Chains to a configured trust anchor: {chain[0] if chain else 'anchor'}.",
            )
        )
    elif not roots:
        checks.append(
            Check(
                **base,
                state=S.INCONCLUSIVE,
                code="no_trust_anchors_configured",
                evidence=t_evidence,
                summary="No trust anchors are configured, so the signer's identity can't be confirmed. "
                "The certificate details below are claims made by the certificate itself.",
                limitations=["Configure VERIFYFLOW_TRUST_ROOTS_DIR with the issuers you trust."],
            )
        )
    elif isinstance(st.trust_problem_indic, AdESFailure):
        checks.append(
            Check(
                **base,
                state=S.FAILED,
                code=f"ades_failure_{indic.lower()}",
                evidence=t_evidence,
                summary=f"Certificate validation failed ({indic}).",
            )
        )
    elif st.trust_problem_indic == AdESIndeterminate.NO_CERTIFICATE_CHAIN_FOUND:
        checks.append(
            Check(
                **base,
                state=S.INCONCLUSIVE,
                code="untrusted_chain",
                evidence=t_evidence,
                summary="The certificate does not chain to any configured trust anchor. The signer's "
                "identity is unconfirmed (it may be self-signed or from an issuer this deployment doesn't "
                "trust).",
            )
        )
    elif indic == "CERTIFICATE_CHAIN_GENERAL_FAILURE":
        checks.append(
            Check(
                **base,
                state=S.INCONCLUSIVE,
                code="chain_validation_error",
                evidence=t_evidence,
                summary="A certificate chain was found but could not be validated: for example, a certificate that "
                "names a trusted issuer but was not signed by that issuer's key. The signer's identity is not "
                "confirmed.",
            )
        )
    elif indic in ("OUT_OF_BOUNDS_NO_POE", "OUT_OF_BOUNDS_NOT_REVOKED"):
        checks.append(
            Check(
                **base,
                state=S.INCONCLUSIVE,
                code="certificate_outside_validity",
                evidence=t_evidence,
                summary="The signer certificate was outside its validity period at validation time, and "
                "no trusted timestamp proves the signature was made while it was valid.",
            )
        )
    else:
        checks.append(
            Check(
                **base,
                state=S.INCONCLUSIVE,
                code=f"indeterminate_{(indic or 'unknown').lower()}",
                evidence=t_evidence,
                summary=f"Certificate trust could not be determined ({indic}).",
            )
        )

    # ---- revocation
    base = _base(D.REVOCATION, field_name, f"Revocation status of “{field_name}” signer")
    material = opts.material
    sources = (["offline CRLs"] if material.crls else []) + (["online OCSP/CRL"] if opts.revocation_fetching else [])
    if not trusted:
        checks.append(
            Check(
                **base,
                state=S.INCONCLUSIVE,
                code="no_trusted_chain",
                summary="Revocation can't be assessed without a trusted certificate chain.",
            )
        )
    elif not sources:
        checks.append(
            Check(
                **base,
                state=S.UNSUPPORTED,
                code="revocation_not_configured",
                summary="No revocation data is configured: no offline CRLs, and online OCSP/CRL fetching "
                "is disabled. Whether the certificate was revoked is unknown.",
                limitations=[
                    "Configure VERIFYFLOW_TRUST_CRL_DIR, or enable "
                    "VERIFYFLOW_TRUST_REVOCATION_FETCHING with controlled network egress."
                ],
            )
        )
    else:
        r_evidence = {"sources": sources, "indication": None}
        try:
            st2 = _validate(
                sig,
                roots,
                crls=list(material.crls),
                allow_fetching=opts.revocation_fetching,
                # Revocation data is required for every non-anchor certificate, even when the certificate declares
                # no CRL/OCSP location: "not revoked" is only reported when it is backed by actual revocation data.
                revinfo_policy=CertRevTrustPolicy(REQUIRE_REVINFO),
            )
            r_evidence["indication"] = _indication(st2)
            if st2.revoked:
                rd = st2.revocation_details
                r_evidence.update(
                    revocation_date=rd.revocation_date.isoformat() if rd.revocation_date else None,
                    reason=str(rd.revocation_reason.native) if rd.revocation_reason else None,
                    ca_revoked=rd.ca_revoked,
                )
                checks.append(
                    Check(
                        **base,
                        state=S.FAILED,
                        code="revoked",
                        evidence=r_evidence,
                        summary="The signing certificate (or its issuer) is revoked. Without a trusted "
                        "timestamp proving the signature predates revocation, it can't be relied on.",
                    )
                )
            elif st2.trusted:
                checks.append(
                    Check(
                        **base,
                        state=S.VERIFIED,
                        code="not_revoked",
                        evidence=r_evidence,
                        establishes="Revocation data from the listed sources shows the certificate "
                        "chain was not revoked at validation time.",
                        limitations=[
                            "Revocation data reflects the time it was issued (CRL " "thisUpdate / OCSP producedAt)."
                        ],
                        summary=f"Not revoked according to {', '.join(sources)}.",
                    )
                )
            else:
                checks.append(
                    Check(
                        **base,
                        state=S.INCONCLUSIVE,
                        code="revocation_unavailable",
                        evidence=r_evidence,
                        summary="Revocation status could not be obtained (no matching CRL, or the "
                        "revocation service was unreachable or returned unusable data).",
                    )
                )
        except (PathBuildingError, SignatureValidationError, ValueError, OSError) as exc:
            log.warning("revocation check failed: %s", exc.__class__.__name__)
            r_evidence["error"] = exc.__class__.__name__
            checks.append(
                Check(
                    **base,
                    state=S.INCONCLUSIVE,
                    code="revocation_unavailable",
                    evidence=r_evidence,
                    summary="Revocation status could not be obtained; the check did not complete.",
                )
            )

    # ---- timestamp
    base = _base(D.TIMESTAMP, field_name, f"Timestamp of “{field_name}”")
    tsv = st.timestamp_validity
    if tsv is None:
        claimed = detail["signer_reported_time"]
        checks.append(
            Check(
                **base,
                state=S.INCONCLUSIVE,
                code="no_timestamp",
                evidence={"signer_reported_time": claimed},
                summary="No timestamp token is embedded. The signing time"
                + (f" ({claimed})" if claimed else "")
                + " is self-reported by the signer and unverified.",
            )
        )
    else:
        ts_ev = {
            "timestamp": tsv.timestamp.isoformat(),
            "tsa": tsv.signing_cert.subject.human_friendly,
            "intact": tsv.intact,
            "valid": tsv.valid,
            "indication": _indication(tsv),
        }
        detail["timestamp"] = ts_ev
        if not (tsv.intact and tsv.valid):
            checks.append(
                Check(
                    **base,
                    state=S.FAILED,
                    code="timestamp_invalid",
                    evidence=ts_ev,
                    summary="The embedded timestamp token does not verify.",
                )
            )
        elif tsv.trusted:
            checks.append(
                Check(
                    **base,
                    state=S.VERIFIED,
                    code="trusted_timestamp",
                    evidence=ts_ev,
                    establishes=f"A trusted timestamp authority attests the signature existed at "
                    f"{ts_ev['timestamp']}.",
                    summary=f"Signature existed at {ts_ev['timestamp']} (trusted TSA).",
                )
            )
        else:
            checks.append(
                Check(
                    **base,
                    state=S.INCONCLUSIVE,
                    code="untrusted_timestamp",
                    evidence=ts_ev,
                    summary="A timestamp is present and intact, but its authority does not chain to a "
                    "configured trust anchor, so the time is unconfirmed.",
                )
            )
    return checks, detail
