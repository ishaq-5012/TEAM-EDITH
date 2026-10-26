"""Sign Harborview's institution-prepared PDFs with an explicitly local certificate chain.

The private keys exist only during this run. The public root and CRL are installed for
this local VerifyFlow deployment; this is not an external regulator's credential.
"""

import io
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from asn1crypto import keys as a_keys
from asn1crypto import x509 as a_x509
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign import signers, timestamps
from pyhanko_certvalidator.registry import SimpleCertificateStore

ROOT = Path(r"E:\sih 2\mock-aicte-portal\institution_packages\Harborview Institute of Engineering")
TRUST = Path(r"E:\sih 2\backend\var\institution-trust")


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
            serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()))


def name(cn: str) -> x509.Name:
    return x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, cn),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Harborview Institute of Engineering"),
    ])


def issue(cn: str, issuer: Identity | None = None, *, ca: bool = False, tsa: bool = False) -> Identity:
    now = datetime.now(UTC)
    key = rsa.generate_private_key(65537, 2048) if tsa else ec.generate_private_key(ec.SECP256R1())
    builder = (x509.CertificateBuilder().subject_name(name(cn))
        .issuer_name(issuer.cert.subject if issuer else name(cn))
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(True, not ca and not tsa, False, False, False,
                                     ca, ca, False, False), critical=True))
    if tsa:
        builder = builder.add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.TIME_STAMPING]), critical=True)
    return Identity(key, builder.sign(issuer.key if issuer else key, hashes.SHA256()))


def sign(pdf: bytes, root: Identity, signer: Identity, tsa: Identity) -> bytes:
    certificates = SimpleCertificateStore.from_certs([root.asn1])
    signing_identity = signers.SimpleSigner(signer.asn1, signer.asn1_key, cert_registry=certificates)
    stamper = timestamps.DummyTimeStamper(
        tsa_cert=tsa.asn1, tsa_key=tsa.asn1_key,
        certs_to_embed=SimpleCertificateStore.from_certs([root.asn1]))
    output = io.BytesIO()
    signers.sign_pdf(IncrementalPdfFileWriter(io.BytesIO(pdf)),
        signers.PdfSignatureMetadata(field_name="InstitutionSignature"),
        signer=signing_identity, timestamper=stamper, output=output)
    return output.getvalue()


def main() -> None:
    files = sorted(ROOT.rglob("*.pdf"))
    if len(files) != 61:
        raise RuntimeError(f"Expected 61 Harborview PDFs, found {len(files)}")
    refresh = sys.argv[1:] == ["--refresh-layout"]
    if (TRUST / "roots" / "harborview-root.pem").exists() and not refresh:
        raise FileExistsError("This signing identity was already installed; refusing to replace it")
    if refresh:
        previews = []
        for path in files:
            # Folder names are display names; category IDs are recorded in input.txt.
            category_id = next(line.split(": ", 1)[1] for line in (path.parent / "input.txt").read_text(encoding="utf-8").splitlines() if line.startswith("CATEGORY ID: "))
            preview = Path(tempfile.gettempdir()) / f"harborview-test-{category_id}-{path.stem}.pdf"
            if not preview.is_file():
                raise FileNotFoundError(preview)
            previews.append((path, preview.read_bytes()))
    else:
        previews = [(path, path.read_bytes()) for path in files]
    root = issue("Harborview Local Document Trust Root", ca=True)
    signer = issue("Harborview Registrar Office Document Signer", root)
    tsa = issue("Harborview Internal Timestamp Service", root, tsa=True)
    signed = [(path, sign(data, root, signer, tsa)) for path, data in previews]
    (TRUST / "roots").mkdir(parents=True, exist_ok=True)
    (TRUST / "crls").mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    revocation_list = (x509.CertificateRevocationListBuilder().issuer_name(root.cert.subject)
        .last_update(now - timedelta(minutes=5)).next_update(now + timedelta(days=365))
        .sign(root.key, hashes.SHA256()))
    (TRUST / "roots" / "harborview-root.pem").write_bytes(root.cert.public_bytes(serialization.Encoding.PEM))
    (TRUST / "crls" / "harborview.crl").write_bytes(revocation_list.public_bytes(serialization.Encoding.DER))
    for path, data in signed:
        path.write_bytes(data)
    print(f"Signed {len(signed)} PDFs; public trust material installed in {TRUST}")


if __name__ == "__main__":
    main()
