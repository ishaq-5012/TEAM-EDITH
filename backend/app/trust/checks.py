"""Check results and the vocabulary shared by every trust dimension."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class State(StrEnum):
    VERIFIED = "verified"  # the check ran and positively confirmed what it tests
    FAILED = "failed"  # the check ran and found a definite problem
    UNSUPPORTED = "unsupported"  # this deployment cannot perform the check for this file or configuration
    INCONCLUSIVE = "inconclusive"  # the check ran but could not reach a verdict


class Dimension(StrEnum):
    FILE_INTEGRITY = "file_integrity"
    SIGNATURE_INTEGRITY = "signature_integrity"
    CERTIFICATE_TRUST = "certificate_trust"
    REVOCATION = "revocation"
    TIMESTAMP = "timestamp"
    EXTERNAL_REGISTRY = "external_registry"


DIMENSION_ORDER = list(Dimension)

# Aggregation: a dimension is only "verified" when every check in it is verified.
_PRECEDENCE = [State.FAILED, State.INCONCLUSIVE, State.UNSUPPORTED, State.VERIFIED]


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class Check:
    dimension: Dimension
    key: str
    label: str
    state: State
    code: str
    method: str
    summary: str
    establishes: str = ""
    does_not_establish: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    subject: str | None = None  # e.g. the signature field name the check is about
    checked_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["dimension"] = self.dimension.value
        d["state"] = self.state.value
        return d


def summarize(checks: list[dict]) -> dict[str, str]:
    """Per-dimension state, worst first. There is deliberately no overall verdict."""
    out: dict[str, str] = {}
    for dim in DIMENSION_ORDER:
        states = {c["state"] for c in checks if c["dimension"] == dim.value}
        if states:
            out[dim.value] = next(s.value for s in _PRECEDENCE if s.value in states)
    return out


# What each dimension never proves, stated on every result.
NOT_ESTABLISHED = {
    Dimension.FILE_INTEGRITY: [
        "who created or issued the document",
        "that the document's contents are true",
        "whether the file was altered before it was uploaded",
    ],
    Dimension.SIGNATURE_INTEGRITY: [
        "that the document's contents are true",
        "that the signer was entitled to sign it",
        "anything about content outside the signed byte range",
    ],
    Dimension.CERTIFICATE_TRUST: [
        "that the document's contents are true",
        "that the signing key was not misused",
        "trust beyond the anchors this deployment is configured with",
    ],
    Dimension.REVOCATION: ["that the document's contents are true"],
    Dimension.TIMESTAMP: ["that the document's contents are true", "when the document's content was authored"],
    Dimension.EXTERNAL_REGISTRY: [
        "that this particular file or paper document is genuine",
        "anything the registry record does not contain",
    ],
}
