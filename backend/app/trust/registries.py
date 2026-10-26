"""Issuer / registry verification through approved, documented integrations only.

A connector is used only when it is listed in VERIFYFLOW_REGISTRY_CONNECTORS. Shipped connectors:

- ``synthetic``: a local JSON file of invented records (app/trust/synthetic_registry.json by default) for
  development and tests. It is refused in production, and every result says it is synthetic.
- ``http_json``: an issuer or registry HTTPS endpoint you have approved and configured
  (VERIFYFLOW_REGISTRY_HTTP_URL). It requires external infrastructure and an agreement with the registry.
  Request: GET {url}?document_number=…  Response: {"found": bool, "status": "valid"|"revoked"|…,
  "record": {"full_name": …, "date_of_birth": …}} — anything else is treated as inconclusive.

Absence from a registry is never reported as a failure: "not found" is inconclusive.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.trust.checks import NOT_ESTABLISHED, Check, Dimension, State

D, S = Dimension, State
DEFAULT_SYNTHETIC = Path(__file__).with_name("synthetic_registry.json")
COMPARED = ("full_name", "date_of_birth")


@dataclass
class Fields:
    """Current effective values (corrections take precedence) extracted from the document."""

    values: dict[str, str]


def _base(key: str, name: str, method: str) -> dict:
    return {
        "dimension": D.EXTERNAL_REGISTRY,
        "key": f"external_registry:{key}",
        "label": name,
        "subject": key,
        "method": method,
        "does_not_establish": NOT_ESTABLISHED[D.EXTERNAL_REGISTRY],
    }


def _compare(record: dict, fields: Fields) -> tuple[list[str], list[str]]:
    matched, mismatched = [], []
    for k in COMPARED:
        doc, reg = fields.values.get(k), record.get(k)
        if doc is None or reg is None:
            continue
        (matched if doc.strip().casefold() == str(reg).strip().casefold() else mismatched).append(k)
    return matched, mismatched


def _judge(
    base: dict, number: str, found: bool, status: str | None, record: dict, fields: Fields, limitations: list[str]
) -> Check:
    ev = {"document_number": number, "found": found, "status": status}
    if not found:
        return Check(
            **base,
            state=S.INCONCLUSIVE,
            code="not_found",
            evidence=ev,
            limitations=limitations,
            summary="The registry has no record for this document number. Absence from a registry is not "
            "proof of forgery (the record may be missing, or the number misread).",
        )
    matched, mismatched = _compare(record, fields)
    ev.update(
        matched_fields=matched, mismatched_fields=mismatched, registry_values={k: record.get(k) for k in mismatched}
    )
    if status and status != "valid":
        return Check(
            **base,
            state=S.FAILED,
            code=f"registry_status_{status}",
            evidence=ev,
            limitations=limitations,
            summary=f"The registry reports this document number as “{status}”.",
        )
    if mismatched:
        return Check(
            **base,
            state=S.FAILED,
            code="registry_mismatch",
            evidence=ev,
            limitations=limitations,
            summary="The registry record differs from the document for: " + ", ".join(mismatched) + ".",
        )
    if not matched:
        return Check(
            **base,
            state=S.INCONCLUSIVE,
            code="nothing_to_compare",
            evidence=ev,
            limitations=limitations,
            summary="A record exists, but none of the compared fields could be checked against it.",
        )
    return Check(
        **base,
        state=S.VERIFIED,
        code="registry_match",
        evidence=ev,
        limitations=limitations,
        establishes="The registry holds a valid record with this document number whose "
        + " and ".join(matched)
        + " match the document.",
        summary="Registry record found and the compared details match.",
    )


class SyntheticRegistry:
    key = "synthetic"
    name = "Synthetic test registry (not a real issuer)"
    method = "Lookup in a local file of invented records"
    requires_external = False

    def __init__(self, path: Path | None = None):
        self.path = path or DEFAULT_SYNTHETIC

    def check(self, fields: Fields) -> Check:
        base = _base(self.key, self.name, self.method)
        limitations = [
            "SYNTHETIC: this registry contains invented records for testing; a match proves nothing "
            "about any real document."
        ]
        number = fields.values.get("document_number")
        if not number:
            return Check(
                **base,
                state=S.UNSUPPORTED,
                code="no_document_number",
                limitations=limitations,
                summary="No document number was extracted, so the registry can't be queried.",
            )
        try:
            records = json.loads(self.path.read_text(encoding="utf-8"))["records"]
        except (OSError, ValueError, KeyError) as exc:
            return Check(
                **base,
                state=S.INCONCLUSIVE,
                code="registry_unavailable",
                limitations=limitations,
                evidence={"error": exc.__class__.__name__},
                summary="The synthetic registry file could not be read.",
            )
        rec = next((r for r in records if str(r.get("document_number", "")).casefold() == number.casefold()), None)
        return _judge(base, number, rec is not None, (rec or {}).get("status"), rec or {}, fields, limitations)


class HttpJsonRegistry:
    key = "http_json"
    method = "HTTPS query to an approved issuer/registry endpoint"
    requires_external = True

    def __init__(self, url: str, timeout: float, name: str):
        self.url, self.timeout, self.name = url, timeout, name

    def check(self, fields: Fields) -> Check:
        base = _base(self.key, self.name, self.method)
        limitations = [f"Result reflects the registry's answer at query time ({self.url.split('?')[0]})."]
        number = fields.values.get("document_number")
        if not number:
            return Check(
                **base,
                state=S.UNSUPPORTED,
                code="no_document_number",
                limitations=limitations,
                summary="No document number was extracted, so the registry can't be queried.",
            )
        try:
            r = httpx.get(self.url, params={"document_number": number}, timeout=self.timeout, follow_redirects=False)
        except httpx.HTTPError as exc:
            return Check(
                **base,
                state=S.INCONCLUSIVE,
                code="registry_unavailable",
                limitations=limitations,
                evidence={"error": exc.__class__.__name__},
                summary="The registry service could not be reached, so nothing was verified.",
            )
        if r.status_code != 200:
            return Check(
                **base,
                state=S.INCONCLUSIVE,
                code="registry_error",
                limitations=limitations,
                evidence={"http_status": r.status_code},
                summary=f"The registry answered HTTP {r.status_code}; nothing was verified.",
            )
        try:
            body = r.json()
            found = body["found"]
            if not isinstance(found, bool):
                raise TypeError
            record = body.get("record") or {}
            status = body.get("status")
            if not isinstance(record, dict) or (status is not None and not isinstance(status, str)):
                raise TypeError
        except (ValueError, KeyError, TypeError):
            return Check(
                **base,
                state=S.INCONCLUSIVE,
                code="registry_bad_response",
                limitations=limitations,
                summary="The registry's response was not in the expected format; nothing was verified.",
            )
        return _judge(base, number, found, status, record, fields, limitations)


def configured(
    names: list[str],
    *,
    environment: str,
    synthetic_path: Path | None,
    http_url: str | None,
    http_timeout: float,
    http_name: str,
) -> list:
    out = []
    for n in names:
        if n == "synthetic" and environment != "production":
            out.append(SyntheticRegistry(synthetic_path))
        elif n == "http_json" and http_url:
            out.append(HttpJsonRegistry(http_url, http_timeout, http_name))
    return out
