"""Create the Harborview institution login once; print its password only at creation."""

import secrets

from app.db import connect
from app.services import register
from tools.build_fourth_institution import INSTITUTION


def main() -> None:
    inst = INSTITUTION
    password = secrets.token_urlsafe(20)
    data = {
        "name": inst["name"], "category": "Engineering & Technology", "ownership": "Private unaided",
        "state": inst["state"], "district": inst["district"], "address": inst["address"],
        "postal_code": inst["address"].split()[-1], "contact_name": "Registrar Office",
        "designation": "Registrar", "email": "registrar.harborview@example.org", "phone": "9000000148",
        "established_year": "2014", "approval_ref": inst["approval"],
        "username": inst["username"], "password": password,
    }
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            register(db, data)
            db.execute("UPDATE institutions SET demo=0 WHERE name=?", (inst["name"],))
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
    print(f"username={inst['username']}")
    print(f"password={password}")


if __name__ == "__main__":
    main()
