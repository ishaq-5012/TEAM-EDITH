"""Provision separate, opt-in institution walkthrough logins without changing existing passwords."""

import json
import secrets

from werkzeug.security import check_password_hash, generate_password_hash

from app.db import DATA, connect
from app.services import now, row, uid

ACCOUNTS = (
    ("Aster Valley Institute of Technology", "evaluator_aster", "Aster Valley"),
    ("Cedar Crest Polytechnic", "evaluator_cedar", "Cedar Crest"),
    ("Meridian School of Computing", "evaluator_meridian", "Meridian"),
    ("Harborview Institute of Engineering", "evaluator_harborview", "Harborview"),
)
FILE = DATA / "evaluator-accounts.json"


def main() -> None:
    if FILE.exists():
        saved = json.loads(FILE.read_text(encoding="utf-8"))
        with connect() as db:
            if len(saved) != len(ACCOUNTS) or any(
                not (user := row(db, "SELECT * FROM users WHERE username=?", (entry["username"],)))
                or not user["active"] or not check_password_hash(user["password_hash"], entry["password"])
                for entry in saved
            ):
                raise RuntimeError("Evaluator credentials no longer match the accounts; inspect before changing them")
        print(f"Evaluator institution accounts already ready: {len(saved)}")
        return
    prepared = []
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            for college, username, label in ACCOUNTS:
                institution = row(db, "SELECT id FROM institutions WHERE name=?", (college,))
                if not institution:
                    raise RuntimeError(f"Institution not found: {college}")
                if row(db, "SELECT id FROM users WHERE username=?", (username,)):
                    raise RuntimeError(f"Evaluator username already exists: {username}")
                password = secrets.token_urlsafe(18)
                db.execute("INSERT INTO users VALUES (?,?,?,?,?,?,?)", (
                    uid(), institution["id"], username, generate_password_hash(password), "institution", 1, now(),
                ))
                prepared.append({"label": label, "username": username, "password": password})
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
    FILE.write_text(json.dumps(prepared, indent=2) + "\n", encoding="utf-8")
    print(f"Created {len(prepared)} evaluator institution accounts in {FILE}")


if __name__ == "__main__":
    main()
