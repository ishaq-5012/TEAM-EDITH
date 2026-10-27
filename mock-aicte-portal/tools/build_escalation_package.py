"""Build the institution-owned records for the one-rule escalation walkthrough.

The generated root and CRL are local demonstration trust material. They do not
represent an approval body or an external issuer. Private signing keys are not saved.
Run once as `python -m tools.build_escalation_package` from the portal directory;
existing output is never replaced.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from asn1crypto import keys as a_keys, x509 as a_x509
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign import signers, timestamps
from pyhanko_certvalidator.registry import SimpleCertificateStore

from app.catalog import get_category
from tools.build_institution_packages import make_pdf

NAME = "Riverton Institute of Technology"
REFERENCE = "RIT-REG-001"
ROOT = Path(__file__).resolve().parents[1] / "institution_packages" / NAME
APPLICATION = ROOT / "01 - New Technical Institution"


@dataclass
class Identity:
    key: object
    cert: x509.Certificate

    @property
    def asn1(self):
        return a_x509.Certificate.load(self.cert.public_bytes(serialization.Encoding.DER))

    @property
    def asn1_key(self):
        return a_keys.PrivateKeyInfo.load(self.key.private_bytes(
            serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ))


def issue(cn: str, issuer: Identity | None = None, *, ca: bool = False, tsa: bool = False) -> Identity:
    now = datetime.now(UTC)
    key = rsa.generate_private_key(65537, 2048) if tsa else ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, cn),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, NAME),
    ])
    builder = (x509.CertificateBuilder().subject_name(name)
        .issuer_name(issuer.cert.subject if issuer else name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(True, not ca and not tsa, False, False, False,
                                     ca, ca, False, False), critical=True))
    if tsa:
        builder = builder.add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.TIME_STAMPING]), critical=True)
    return Identity(key, builder.sign(issuer.key if issuer else key, hashes.SHA256()))


def sign(pdf: bytes, root: Identity, registrar: Identity, tsa: Identity) -> bytes:
    store = SimpleCertificateStore.from_certs([root.asn1])
    signer = signers.SimpleSigner(registrar.asn1, registrar.asn1_key, cert_registry=store)
    timestamper = timestamps.DummyTimeStamper(
        tsa_cert=tsa.asn1, tsa_key=tsa.asn1_key,
        certs_to_embed=SimpleCertificateStore.from_certs([root.asn1]),
    )
    output = io.BytesIO()
    signers.sign_pdf(IncrementalPdfFileWriter(io.BytesIO(pdf)),
        signers.PdfSignatureMetadata(field_name="InstitutionSignature"),
        signer=signer, timestamper=timestamper, output=output)
    return output.getvalue()


def main() -> None:
    if ROOT.exists():
        raise FileExistsError(f"Refusing to replace existing package: {ROOT}")
    APPLICATION.mkdir(parents=True)
    remediation = APPLICATION / "remediation"
    remediation.mkdir()
    institution = {
        "name": NAME, "ref": REFERENCE, "approval": "",
        "programme": "Computer Science and Engineering",
        "address": "18 Knowledge Road, Chennai, Tamil Nadu 600113",
        "district": "Chennai", "state": "Tamil Nadu",
        "affiliation": "Regional Technical University", "faculty": 24, "rooms": 18,
    }
    category = get_category("new")
    form = {
        "programme": institution["programme"], "level": "Undergraduate", "proposed_intake": "60",
        "academic_year": "2026-27",
        "justification": "Proposal for a new technical institution, supported by the enclosed records.",
    }
    root = issue("Riverton Local Document Trust Root", ca=True)
    registrar = issue("Riverton Registrar Office Document Signer", root)
    tsa = issue("Riverton Internal Timestamp Service", root, tsa=True)
    for code in ("registration", "programme", "declaration", "safety"):
        path = (remediation if code == "safety" else APPLICATION) / f"{code}.pdf"
        make_pdf(path, institution, category, form, code, f"{REFERENCE}-NEW-{code.upper()}")
        path.write_bytes(sign(path.read_bytes(), root, registrar, tsa))
    trust = ROOT / "trust"
    trust.mkdir()
    (trust / "riverton-root.pem").write_bytes(root.cert.public_bytes(serialization.Encoding.PEM))
    now = datetime.now(UTC)
    crl = (x509.CertificateRevocationListBuilder().issuer_name(root.cert.subject)
        .last_update(now - timedelta(minutes=5)).next_update(now + timedelta(days=365))
        .sign(root.key, hashes.SHA256()))
    (trust / "riverton.crl").write_bytes(crl.public_bytes(serialization.Encoding.DER))
    (ROOT / "institution.txt").write_text(
        f"Institution name: {NAME}\nInstitution reference: {REFERENCE}\n"
        "Category: Engineering & Technology\nOwnership: Private unaided\n"
        f"Address: {institution['address']}\nEstablished year: 2024\n"
        "Contact: Registrar, office@riverton.example.invalid\n"
        "These are institution-prepared records. The local test trust root is not a regulator credential.\n",
        encoding="utf-8",
    )
    (APPLICATION / "input.txt").write_text(
        "APPLICATION: New Technical Institution\nCATEGORY ID: new\n"
        f"INSTITUTION: {NAME}\n\nFORM INPUTS\n"
        + "\n".join(f"{key}: {value}" for key, value in form.items())
        + "\ndeclaration: Yes\n\nINITIAL UPLOAD\n"
        "registration: registration.pdf\nprogramme: programme.pdf\ndeclaration: declaration.pdf\n\n"
        "ESCALATION\nThe published internal evidence-set rule asks for four supporting files. "
        "This submission contains three, so the reviewer can escalate the rule finding.\n\n"
        "REMEDIATION FILE\nremediation/safety.pdf is prepared but must not be uploaded initially.\n",
        encoding="utf-8",
    )
    print(f"Prepared {NAME}: three initial PDFs, one remediation PDF, public trust material")


if __name__ == "__main__":
    main()
