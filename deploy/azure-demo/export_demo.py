"""Export a consistent, small snapshot of the current SIH evaluator data.

Run from the repository root: py -3.11 deploy/azure-demo/export_demo.py
Do not upload real personal documents to a public evaluator server.
"""

from __future__ import annotations

import hashlib
import sqlite3
import tarfile
import tempfile
from pathlib import Path
from shutil import copy2, copytree


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "deploy" / "azure-demo" / "demo-data.tar.gz"


def backup_sqlite(source: Path, target: Path) -> None:
    if not source.is_file():
        raise SystemExit(f"Missing local database: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as connection, sqlite3.connect(target) as snapshot:
        connection.backup(snapshot)


def copy_required(source: Path, target: Path) -> None:
    if not source.exists():
        raise SystemExit(f"Missing evaluator data: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        copytree(source, target)
    else:
        copy2(source, target)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="sih-export-") as scratch:
        stage = Path(scratch)
        backend = ROOT / "backend" / "var"
        portal = ROOT / "mock-aicte-portal" / "var"
        backup_sqlite(backend / "verifyflow.db", stage / "backend/var/verifyflow.db")
        backup_sqlite(portal / "portal.sqlite3", stage / "mock-aicte-portal/var/portal.sqlite3")
        for name in ("storage", "institution-trust", "demo-accounts.txt"):
            copy_required(backend / name, stage / "backend/var" / name)
        for name in ("uploads", "evaluator-accounts.json"):
            copy_required(portal / name, stage / "mock-aicte-portal/var" / name)
        with tarfile.open(OUT, "w:gz") as archive:
            archive.add(stage / "backend/var", arcname="backend/var")
            archive.add(stage / "mock-aicte-portal/var", arcname="mock-aicte-portal/var")
    digest = hashlib.sha256(OUT.read_bytes()).hexdigest()
    print(f"Created {OUT} ({OUT.stat().st_size:,} bytes)")
    print(f"SHA-256: {digest}")
    print("This archive contains credentials and documents. Transfer it privately; never commit it.")


if __name__ == "__main__":
    main()
