"""Trust anchors and offline revocation data configured by the deployment.

Nothing is trusted by default: without configured anchors, certificate trust is reported as inconclusive.
Files are read from directories set in configuration; invalid files are reported, never silently skipped.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from asn1crypto import crl as a_crl
from asn1crypto import pem
from asn1crypto import x509 as a_x509

CERT_SUFFIXES = {".pem", ".crt", ".cer", ".der"}
CRL_SUFFIXES = {".crl", ".pem", ".der"}
MAX_FILES = 200
MAX_BYTES = 1024 * 1024


@dataclass
class TrustMaterial:
    roots: list[a_x509.Certificate] = field(default_factory=list)
    crls: list[a_crl.CertificateList] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def describe(self) -> dict:
        return {
            "trust_anchors": [
                {
                    "subject": c.subject.human_friendly,
                    "sha256": hashlib.sha256(c.dump()).hexdigest(),
                    "not_after": c["tbs_certificate"]["validity"]["not_after"].native.isoformat(),
                }
                for c in self.roots
            ],
            "crls": [
                {
                    "issuer": c.issuer.human_friendly,
                    "next_update": c["tbs_cert_list"]["next_update"].native.isoformat()
                    if c["tbs_cert_list"]["next_update"].native
                    else None,
                }
                for c in self.crls
            ],
            "problems": self.problems,
        }


def _blobs(path: Path, suffixes: set[str], problems: list[str]) -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    files = sorted(p for p in path.iterdir() if p.is_file() and p.suffix.lower() in suffixes)[:MAX_FILES]
    for f in files:
        data = f.read_bytes()
        if len(data) > MAX_BYTES:
            problems.append(f"{f.name}: larger than {MAX_BYTES} bytes, ignored")
            continue
        if pem.detect(data):
            out += [(f.name, der) for _, _, der in pem.unarmor(data, multiple=True)]
        else:
            out.append((f.name, data))
    return out


def load(roots_dir: Path | None, crl_dir: Path | None) -> TrustMaterial:
    tm = TrustMaterial()
    if roots_dir is not None:
        if not roots_dir.is_dir():
            tm.problems.append(f"trust anchor directory not found: {roots_dir.name}")
        else:
            for name, der in _blobs(roots_dir, CERT_SUFFIXES, tm.problems):
                try:
                    cert = a_x509.Certificate.load(der)
                    cert.native  # noqa: B018 - force a full parse so malformed files are reported here
                    tm.roots.append(cert)
                except ValueError as exc:
                    tm.problems.append(f"{name}: not a valid X.509 certificate ({exc.__class__.__name__})")
    if crl_dir is not None:
        if not crl_dir.is_dir():
            tm.problems.append(f"CRL directory not found: {crl_dir.name}")
        else:
            for name, der in _blobs(crl_dir, CRL_SUFFIXES, tm.problems):
                try:
                    c = a_crl.CertificateList.load(der)
                    c.native  # noqa: B018
                    tm.crls.append(c)
                except ValueError as exc:
                    tm.problems.append(f"{name}: not a valid CRL ({exc.__class__.__name__})")
    return tm
