"""Operator CLI.

    python -m app.cli bootstrap-dev-admin --email you@example.com      # development only
    python -m app.cli create-user --email you@example.org --name "Your Name" --role admin
    python -m app.cli worker                                           # VERIFYFLOW_PROCESSING_MODE=worker

bootstrap-dev-admin works only with VERIFYFLOW_ENVIRONMENT=development on an empty database.
It prints a one-time random password and stores it nowhere.

create-user reads the password interactively (never echoed), or from the
VERIFYFLOW_BOOTSTRAP_PASSWORD environment variable for scripted setups.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from app.core.errors import DomainError
from app.core.roles import Role
from app.core.security import password_strength_error
from app.db.session import SessionLocal
from app.services import audit_service, institution_service, user_service
from app.services.audit_service import AuditContext


def _read_password() -> str:
    env = os.environ.get("VERIFYFLOW_BOOTSTRAP_PASSWORD")
    if env:
        return env
    first = getpass.getpass("Password: ")
    if first != getpass.getpass("Confirm password: "):
        sys.exit("Passwords do not match")
    return first


def create_institution(args: argparse.Namespace) -> int:
    with SessionLocal() as db:
        try:
            inst = institution_service.create(db, AuditContext(request_id="cli"), name=args.name, code=args.code)
            db.commit()
        except DomainError as exc:
            print(f"Error: {exc.message}", file=sys.stderr)
            return 1
    print(f"Created institution {inst.code} ({inst.name})")
    return 0


def create_user(args: argparse.Namespace) -> int:
    password = _read_password()
    err = password_strength_error(password)
    if err:
        print(err, file=sys.stderr)
        return 2
    with SessionLocal() as db:
        try:
            institution_id = None
            if args.institution:
                inst = institution_service.get_by_code(db, args.institution)
                if inst is None:
                    print(f"Error: no institution with code {args.institution.upper()}", file=sys.stderr)
                    return 1
                institution_id = inst.id
            user = user_service.create_user(
                db, AuditContext(request_id="cli"),
                email=args.email, full_name=args.name, role=Role(args.role), password=password,
                institution_id=institution_id,
            )
            db.commit()
        except DomainError as exc:
            print(f"Error: {exc.message}", file=sys.stderr)
            return 1
    print(f"Created {user.role} user {user.email} ({user.id})")
    return 0


def bootstrap_dev_admin(args: argparse.Namespace) -> int:
    with SessionLocal() as db:
        try:
            user, password = user_service.bootstrap_dev_admin(
                db, AuditContext(request_id="cli-bootstrap"), email=args.email, full_name=args.name
            )
        except DomainError as exc:
            print(f"Error: {exc.message}", file=sys.stderr)
            return 1
    # Shown exactly once and never stored. Change it after first sign-in (Account page).
    print(f"Created development administrator {user.email}")
    print(f"One-time password: {password}")
    print("This password is not saved anywhere. Sign in and change it from the Account page.")
    return 0


def make_demo_files(args: argparse.Namespace) -> int:
    """Write clearly-labelled synthetic sample documents for manual testing. No real data."""
    from app.services.demo_files import write_demo_files

    out = Path(args.out).resolve()
    for path, purpose in write_demo_files(out):
        print(f"{path.name:<34} {purpose}")
    print()
    print(f"Wrote synthetic files to {out}")
    return 0


def make_trust_fixtures(args: argparse.Namespace) -> int:
    """Write a synthetic root certificate and signed / unsigned / tampered PDFs for trying the Trust Center."""
    from app.trust.synthetic_pki import SyntheticPKI, append_unpermitted_update, issue, unsigned_pdf

    out = Path(args.out).resolve()
    (out / "trust-roots").mkdir(parents=True, exist_ok=True)
    lines = ["Full name: Test Person Alpha", "Date of birth: 03 March 1990", "Document number: SYN-000123"]
    pki = SyntheticPKI.create(with_tsa=True)
    rogue_root = issue("Unrelated Synthetic Root", ca=True)
    rogue = SyntheticPKI(root=rogue_root, signer=issue("Untrusted Synthetic Signer", rogue_root))
    signed = pki.sign(unsigned_pdf(lines))
    files = {
        "signed-trusted.pdf": (signed, "signed by the synthetic root's signer"),
        "signed-timestamped.pdf": (pki.sign(unsigned_pdf(lines), timestamp=True), "signed and timestamped"),
        "signed-then-modified.pdf": (append_unpermitted_update(signed), "changed after signing"),
        "signed-untrusted.pdf": (rogue.sign(unsigned_pdf(lines)), "signed by an issuer you have not trusted"),
        "unsigned.pdf": (unsigned_pdf(lines), "no signature"),
    }
    for name, (data, purpose) in files.items():
        (out / name).write_bytes(data)
        print(f"{name:<26} {purpose}")
    (out / "trust-roots" / "synthetic-root.pem").write_bytes(pki.root.pem())
    print()
    print(f"Wrote synthetic files to {out} (private keys were never written).")
    print(f"To trust the synthetic root in development: VERIFYFLOW_TRUST_ROOTS_DIR={out / 'trust-roots'}")
    return 0


def seed_demo(args: argparse.Namespace) -> int:
    """Development only: create labelled synthetic applications and run them through the real pipeline."""
    from app.db.session import get_session_factory
    from app.services.demo_seed import seed_demo as run_seed
    from app.services.storage import get_storage

    try:
        rows = run_seed(get_session_factory(), get_storage(), args.owner_email)
    except DomainError as exc:
        print(f"Error: {exc.message}", file=sys.stderr)
        return 1
    for r in rows:
        print(f"{r['reference']}  {r['title']}  validation: {r.get('validation')}")
    print()
    print("These applications are flagged is_synthetic and labelled 'Synthetic demo' in the UI.")
    return 0


# Development-only demo accounts: (email, full name, role, institution code).
_DEMO_ACCOUNTS = [
    ("compliance.manager@example.org", "Demo Compliance Manager", Role.COMPLIANCE_MANAGER, "DEFAULT"),
    ("reviewer.demo@example.org", "Demo Reviewer", Role.REVIEWER, "DEFAULT"),
    ("auditor.demo@example.org", "Demo Auditor", Role.AUDITOR, "DEFAULT"),
    ("admin.collegeb@example.org", "College B Administrator", Role.ADMIN, "COLLEGE-B"),
    ("reviewer.collegeb@example.org", "College B Reviewer", Role.REVIEWER, "COLLEGE-B"),
]


def seed_demo_users(args: argparse.Namespace) -> int:
    """Create one demo account per role, in two institutions, with generated passwords written to a file.

    Development only. Passwords are never printed: they go to the output file, which lives under var/ (not committed).
    Existing accounts are left untouched (their passwords are not changed or shown).
    """
    from app.core.config import get_settings

    if get_settings().environment != "development":
        print("Error: seed-demo-users only runs when VERIFYFLOW_ENVIRONMENT=development", file=sys.stderr)
        return 1
    out = Path(args.out)
    header = [
        "VerifyFlow demo accounts (DEVELOPMENT ONLY - synthetic, delete or rotate anytime)",
        "Sign in at http://localhost:5173. Passwords were generated once and are not stored anywhere else.",
        "",
    ]
    lines: list[str] = []  # only accounts created by this run; an existing credentials file is appended to, never rewritten
    created = skipped = 0
    with SessionLocal() as db:
        ctx = AuditContext(request_id="cli-seed-users")
        institutions: dict[str, str] = {}
        for _email, _name, _role, code in _DEMO_ACCOUNTS:
            if code in institutions:
                continue
            inst = institution_service.get_by_code(db, code)
            if inst is None:
                inst = institution_service.create(db, ctx, name="Synthetic College B" if code == "COLLEGE-B" else "Default institution", code=code)
            institutions[code] = inst.id
        db.commit()
        for email, name, role, code in _DEMO_ACCOUNTS:
            if user_service.get_by_email(db, email):
                skipped += 1
                continue
            password = user_service.generate_password()
            user_service.create_user(
                db, ctx, email=email, full_name=name, role=role, password=password, institution_id=institutions[code]
            )
            db.commit()
            lines.append(f"{role.value:20} {email:34} password: {password}  institution {code}")
            created += 1
    if lines:
        out.parent.mkdir(parents=True, exist_ok=True)
        text = chr(10).join(lines) + chr(10)
        if out.exists():
            out.write_text(out.read_text(encoding="utf-8").rstrip(chr(10)) + chr(10) + text, encoding="utf-8")
        else:
            out.write_text(chr(10).join(header) + chr(10) + text, encoding="utf-8")
    print(f"Created {created} account(s), skipped {skipped} that already existed (their passwords are unchanged).")
    if created:
        print(f"Credentials were written to {out}")
    return 0


def verify_audit(_: argparse.Namespace) -> int:
    with SessionLocal() as db:
        result = audit_service.verify_chain(db)
    print(result)
    return 0 if result.valid else 1


def worker(args: argparse.Namespace) -> int:
    """Run queued processing jobs from the database until interrupted (SIGINT/SIGTERM), or one pass with --once."""
    import signal
    import threading

    from app.core.config import get_settings
    from app.core.logging import configure_logging
    from app.db.session import get_session_factory
    from app.services import worker as worker_service
    from app.services.storage import get_storage

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    if settings.processing_mode != "worker":
        print("Note: VERIFYFLOW_PROCESSING_MODE is not 'worker', so the API also runs jobs itself.", file=sys.stderr)
    factory, storage = get_session_factory(), get_storage()
    if args.once:
        print(f"Attempted {worker_service.run_once(factory, storage)} queued job(s)")
        return 0
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    worker_service.run_forever(factory, storage, stop)
    return 0


def prune_sessions(args: argparse.Namespace) -> int:
    """Retention: delete session records that ended more than --older-than-days ago (live sessions are kept)."""
    from app.services import session_service

    with SessionLocal() as db:
        removed = session_service.prune_ended(db, AuditContext(request_id="cli"), args.older_than_days)
    print(f"Deleted {removed} ended session record(s)")
    return 0


def verify_storage(_: argparse.Namespace) -> int:
    """Check every document's stored file exists and matches its recorded SHA-256 (e.g. after a restore).
    Prints only counts and document ids, never file names or contents. Exit code 1 if anything is missing or altered."""
    import hashlib

    from sqlalchemy import select

    from app.core.errors import DomainError as _DomainError
    from app.models.application import Document
    from app.services.storage import get_storage

    storage = get_storage()
    checked = missing = altered = 0
    with SessionLocal() as db:
        for doc_id, key, sha in db.execute(select(Document.id, Document.storage_key, Document.sha256)):
            checked += 1
            try:
                data = storage.read(key)
            except _DomainError:
                missing += 1
                print(f"MISSING  document {doc_id}")
                continue
            if hashlib.sha256(data).hexdigest() != sha:
                altered += 1
                print(f"ALTERED  document {doc_id}")
    print(f"Checked {checked} document(s): {missing} missing, {altered} altered")
    return 0 if not (missing or altered) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="verifyflow")
    sub = parser.add_subparsers(dest="cmd", required=True)
    cu = sub.add_parser("create-user", help="Create a user account")
    cu.add_argument("--email", required=True)
    cu.add_argument("--name", required=True)
    cu.add_argument("--role", required=True, choices=[r.value for r in Role])
    cu.add_argument("--institution", help="Institution code (default: DEFAULT)")
    cu.set_defaults(func=create_user)
    ci = sub.add_parser("create-institution", help="Create an institution (a tenant)")
    ci.add_argument("--name", required=True)
    ci.add_argument("--code", required=True, help="Short stable code, e.g. COLLEGE-042")
    ci.set_defaults(func=create_institution)
    bd = sub.add_parser(
        "bootstrap-dev-admin",
        help="Development only: create the first admin with a one-time generated password",
    )
    bd.add_argument("--email", required=True)
    bd.add_argument("--name", default="Development Admin")
    bd.set_defaults(func=bootstrap_dev_admin)
    md = sub.add_parser("make-demo-files", help="Write synthetic sample documents (valid and invalid) for testing")
    md.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "var" / "demo-files"))
    md.set_defaults(func=make_demo_files)
    mt = sub.add_parser("make-trust-fixtures", help="Write a synthetic root and signed/unsigned PDFs (dev only)")
    mt.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "var" / "trust-fixtures"))
    mt.set_defaults(func=make_trust_fixtures)
    sd = sub.add_parser("seed-demo", help="Development only: create labelled synthetic demo applications")
    sd.add_argument("--owner-email", required=True, help="An existing user who can create applications")
    sd.set_defaults(func=seed_demo)
    sdu = sub.add_parser("seed-demo-users", help="Development only: one demo account per role in two institutions")
    sdu.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "var" / "demo-accounts.txt"))
    sdu.set_defaults(func=seed_demo_users)
    va = sub.add_parser("verify-audit", help="Verify the audit hash chain")
    va.set_defaults(func=verify_audit)
    wk = sub.add_parser("worker", help="Run queued document processing jobs (VERIFYFLOW_PROCESSING_MODE=worker)")
    wk.add_argument("--once", action="store_true", help="Run one pass and exit (for cron or smoke tests)")
    wk.set_defaults(func=worker)
    vs = sub.add_parser("verify-storage", help="Check every stored document against its recorded SHA-256")
    vs.set_defaults(func=verify_storage)
    ps = sub.add_parser("prune-sessions", help="Retention: delete session records that ended long ago")
    ps.add_argument("--older-than-days", type=int, default=90, choices=range(1, 3651), metavar="DAYS")
    ps.set_defaults(func=prune_sessions)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
