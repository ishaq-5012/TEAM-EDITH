"""Synthetic PKI and signed PDFs for tests and local demos.

Everything here is invented: a throwaway root CA named "SYNTHETIC TEST ROOT", signer and timestamp certificates,
and PDFs labelled SYNTHETIC. Private keys exist only in memory and are never written to disk. Nothing produced
here should be configured as a trust anchor outside development and testing.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pymupdf
from asn1crypto import keys as a_keys
from asn1crypto import x509 as a_x509
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from pyhanko.pdf_utils import generic
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign import signers, timestamps
from pyhanko_certvalidator.registry import SimpleCertificateStore

BANNER = "SYNTHETIC DEMO DOCUMENT - NOT A REAL RECORD"


def _name(cn: str) -> x509.Name:
    return x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, cn),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "VerifyFlow Synthetic PKI (not real)"),
        ]
    )


@dataclass
class Identity:
    key: object
    cert: x509.Certificate

    @property
    def asn1(self) -> a_x509.Certificate:
        return a_x509.Certificate.load(self.cert.public_bytes(serialization.Encoding.DER))

    @property
    def asn1_key(self) -> a_keys.PrivateKeyInfo:
        return a_keys.PrivateKeyInfo.load(
            self.key.private_bytes(
                serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
        )

    def pem(self) -> bytes:
        return self.cert.public_bytes(serialization.Encoding.PEM)


def issue(
    cn: str,
    issuer: Identity | None = None,
    *,
    ca: bool = False,
    tsa: bool = False,
    not_before: datetime | None = None,
    not_after: datetime | None = None,
    crl_url: str | None = None,
) -> Identity:
    now = datetime.now(UTC)
    key = rsa.generate_private_key(65537, 2048) if tsa else ec.generate_private_key(ec.SECP256R1())
    b = (
        x509.CertificateBuilder()
        .subject_name(_name(cn))
        .issuer_name(issuer.cert.subject if issuer else _name(cn))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before or now - timedelta(days=1))
        .not_valid_after(not_after or now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(True, not ca and not tsa, False, False, False, ca, ca, False, False), critical=True
        )
    )
    if tsa:
        b = b.add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.TIME_STAMPING]), critical=True)
    if crl_url:
        b = b.add_extension(
            x509.CRLDistributionPoints(
                [x509.DistributionPoint([x509.UniformResourceIdentifier(crl_url)], None, None, None)]
            ),
            critical=False,
        )
    cert = b.sign((issuer.key if issuer else key), hashes.SHA256())
    return Identity(key, cert)


def crl(ca: Identity, revoked: list[x509.Certificate] = ()) -> bytes:  # type: ignore[assignment]
    now = datetime.now(UTC)
    b = x509.CertificateRevocationListBuilder().issuer_name(ca.cert.subject).last_update(now - timedelta(hours=1))
    b = b.next_update(now + timedelta(days=7))
    for c in revoked:
        b = b.add_revoked_certificate(
            x509.RevokedCertificateBuilder()
            .serial_number(c.serial_number)
            .revocation_date(now - timedelta(minutes=30))
            .build()
        )
    return b.sign(ca.key, hashes.SHA256()).public_bytes(serialization.Encoding.DER)


def unsigned_pdf(lines: list[str] | None = None) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((56, 60), BANNER, fontsize=12, color=(0.7, 0, 0))
    for i, line in enumerate(lines or ["Full name: Test Person Alpha", "Document number: SYN-000123"]):
        page.insert_text((56, 100 + i * 18), line, fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


@dataclass
class SyntheticPKI:
    root: Identity
    signer: Identity
    tsa: Identity | None = None
    extra: dict[str, Identity] = field(default_factory=dict)

    @classmethod
    def create(cls, *, with_tsa: bool = False, crl_url: str | None = None) -> SyntheticPKI:
        root = issue("SYNTHETIC TEST ROOT", ca=True)
        signer = issue("Synthetic Signer (Test Person Alpha)", root, crl_url=crl_url)
        tsa = issue("Synthetic Timestamp Authority", root, tsa=True) if with_tsa else None
        return cls(root, signer, tsa)

    def sign(
        self, pdf: bytes, *, signer: Identity | None = None, field_name: str = "Signature1", timestamp: bool = False
    ) -> bytes:
        who = signer or self.signer
        s = signers.SimpleSigner(
            signing_cert=who.asn1,
            signing_key=who.asn1_key,
            cert_registry=SimpleCertificateStore.from_certs([self.root.asn1]),
        )
        stamper = None
        if timestamp:
            if self.tsa is None:
                raise ValueError("create the PKI with with_tsa=True to timestamp")
            stamper = timestamps.DummyTimeStamper(
                tsa_cert=self.tsa.asn1,
                tsa_key=self.tsa.asn1_key,
                certs_to_embed=SimpleCertificateStore.from_certs([self.root.asn1]),
            )
        out = io.BytesIO()
        signers.sign_pdf(
            IncrementalPdfFileWriter(io.BytesIO(pdf)),
            signers.PdfSignatureMetadata(field_name=field_name),
            signer=s,
            timestamper=stamper,
            output=out,
        )
        return out.getvalue()


def append_unpermitted_update(signed: bytes) -> bytes:
    """Add an incremental update after signing that a signature does not permit (a new catalog entry)."""
    w = IncrementalPdfFileWriter(io.BytesIO(signed))
    w.root["/SyntheticTamper"] = w.add_object(generic.TextStringObject("changed after signing"))
    w.update_root()
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


def flip_signed_byte(signed: bytes) -> bytes:
    """Corrupt one byte inside the signed range (the PDF header comment) to break the digest."""
    data = bytearray(signed)
    data[20] = (data[20] + 1) % 256
    return bytes(data)
