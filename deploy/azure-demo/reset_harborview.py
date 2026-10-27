"""Remove only Harborview's portal demo submissions and linked VerifyFlow cases.

Run on the VM from the repository root after stopping `portal` and `api`:
    python3 deploy/azure-demo/reset_harborview.py          # inspect target counts
    python3 deploy/azure-demo/reset_harborview.py --execute

The execute mode first backs up both SQLite databases and the target uploads.
Immutable VerifyFlow audit events are retained as the historical record of the
demo reset; all application records and their dependent case records are removed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PORTAL = ROOT / "mock-aicte-portal" / "var"
BACKEND = ROOT / "backend" / "var"
NAME = "Harborview Institute of Engineering"


def quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def chunks(values: set[int], size: int = 400):
    items = sorted(values)
    for i in range(0, len(items), size):
        yield items[i:i + size]


def descendants(db: sqlite3.Connection, application_ids: list[str]) -> dict[str, set[int]]:
    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    edges = []
    for child in tables:
        for _, _, parent, from_col, to_col, *_ in db.execute(f"PRAGMA foreign_key_list({quote(child)})"):
            edges.append((child, parent, from_col, to_col or "id"))
    selected: dict[str, set[int]] = {table: set() for table in tables}
    for app_id in application_ids:
        selected["applications"].update(r[0] for r in db.execute(
            "SELECT rowid FROM applications WHERE id=?", (app_id,)
        ))
    changed = True
    while changed:
        changed = False
        for child, parent, from_col, to_col in edges:
            if not selected.get(parent):
                continue
            values = set()
            for batch in chunks(selected[parent]):
                placeholders = ",".join("?" for _ in batch)
                values.update(r[0] for r in db.execute(
                    f"SELECT {quote(to_col)} FROM {quote(parent)} WHERE rowid IN ({placeholders})", batch
                ) if r[0] is not None)
            if not values:
                continue
            for batch in chunks(values):
                placeholders = ",".join("?" for _ in batch)
                matched = {r[0] for r in db.execute(
                    f"SELECT rowid FROM {quote(child)} WHERE {quote(from_col)} IN ({placeholders})", batch
                )}
                new = matched - selected[child]
                if new:
                    selected[child].update(new)
                    changed = True
    return {table: ids for table, ids in selected.items() if ids}


def delete_selected(db: sqlite3.Connection, selected: dict[str, set[int]]) -> None:
    # The case's immutable history is included in the backup. The DB triggers
    # are temporarily removed only for the rows explicitly selected below.
    protected = [(name, sql) for name, table, sql in db.execute(
        "SELECT name,tbl_name,sql FROM sqlite_master WHERE type='trigger' AND sql IS NOT NULL"
    ) if table in selected and "no_delete" in name]
    db.execute("PRAGMA foreign_keys=OFF")
    db.execute("BEGIN IMMEDIATE")
    try:
        for name, _ in protected:
            db.execute(f"DROP TRIGGER {quote(name)}")
        for table, ids in selected.items():
            for batch in chunks(ids):
                placeholders = ",".join("?" for _ in batch)
                db.execute(f"DELETE FROM {quote(table)} WHERE rowid IN ({placeholders})", batch)
        for _, sql in protected:
            db.execute(sql)
        violations = list(db.execute("PRAGMA foreign_key_check"))
        if violations:
            raise RuntimeError(f"Foreign key violations after reset: {violations[:5]}")
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.execute("PRAGMA foreign_keys=ON")


def main(execute: bool) -> None:
    portal = sqlite3.connect(PORTAL / "portal.sqlite3")
    backend = sqlite3.connect(BACKEND / "verifyflow.db")
    try:
        portal_ids = [r[0] for r in portal.execute(
            "SELECT a.id FROM applications a JOIN institutions i ON i.id=a.institution_id WHERE i.name=?", (NAME,)
        )]
        backend_ids = [r[0] for app_id in portal_ids for r in backend.execute(
            "SELECT application_id FROM portal_submissions WHERE portal_application_id=?", (app_id,)
        )]
        backend_ids = sorted(set(backend_ids))
        portal_rows = descendants(portal, portal_ids)
        backend_rows = descendants(backend, backend_ids)
        # The portal's application audit rows are unlinked by FK but belong to the reset case.
        if portal_ids:
            portal_rows["audit_log"] = {r[0] for app_id in portal_ids for r in portal.execute(
                "SELECT rowid FROM audit_log WHERE application_id=?", (app_id,)
            )}
        portal_rows = {k: v for k, v in portal_rows.items() if v}
        portal_files = [r[0] for app_id in portal_ids for r in portal.execute(
            "SELECT v.stored_name FROM document_versions v JOIN documents d ON d.id=v.document_id "
            "WHERE d.application_id=?", (app_id,)
        )]
        backend_keys = [r[0] for app_id in backend_ids for r in backend.execute(
            "SELECT storage_key FROM documents WHERE application_id=?", (app_id,)
        )]
        print("Harborview portal applications:", len(portal_ids), portal_ids)
        print("Linked VerifyFlow applications:", len(backend_ids), backend_ids)
        print("Portal rows:", {k: len(v) for k, v in sorted(portal_rows.items())})
        print("VerifyFlow rows:", {k: len(v) for k, v in sorted(backend_rows.items())})
        print("Upload files:", len(portal_files), "portal;", len(backend_keys), "VerifyFlow")
        if not execute or not portal_ids:
            return
        stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        backup = ROOT / "deploy" / "azure-demo" / "backups" / f"harborview-reset-{stamp}"
        backup.mkdir(parents=True, exist_ok=False)
        for source, name in ((portal, "portal.sqlite3"), (backend, "verifyflow.db")):
            destination = sqlite3.connect(backup / name)
            try:
                source.backup(destination)
            finally:
                destination.close()
        files = [(PORTAL / "uploads" / name) for name in portal_files]
        files += [(BACKEND / "storage" / key[:2] / key) for key in backend_keys]
        with tarfile.open(backup / "target-uploads.tar.gz", "w:gz") as archive:
            for path in files:
                if path.is_file():
                    archive.add(path, arcname=path.relative_to(ROOT))
        delete_selected(backend, backend_rows)
        delete_selected(portal, portal_rows)
        for path in files:
            path.unlink(missing_ok=True)
        print("Reset complete. Backup:", backup)
    finally:
        backend.close()
        portal.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Back up and remove only Harborview demo cases")
    main(parser.parse_args().execute)
