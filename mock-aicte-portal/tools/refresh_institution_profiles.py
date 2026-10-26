"""Align existing institution accounts with the prepared application packages."""

from app.db import connect
from tools.build_institution_packages import INSTITUTIONS


def main() -> None:
    with connect() as db:
        for inst in INSTITUTIONS:
            db.execute(
                """UPDATE institutions SET state=?, district=?, address=?, postal_code=?,
                   approval_ref=?, demo=0 WHERE name=?""",
                (inst["state"], inst["district"], inst["address"], inst["address"].split()[-1],
                 inst["approval"], inst["name"]),
            )
        for name, district, address, approval in (
            ("Bluehaven Technical College", "Tiruchirappalli", "58 College Road, Tiruchirappalli, Tamil Nadu 620001", "BTC-PRIOR-2025"),
            ("Northstar Design Institute", "Salem", "16 Design Avenue, Salem, Tamil Nadu 636001", "NDI-PRIOR-2025"),
            ("Silverleaf Institute of Management", "Tirunelveli", "42 Education Street, Tirunelveli, Tamil Nadu 627001", "SIM-PRIOR-2025"),
        ):
            db.execute(
                """UPDATE institutions SET state='Tamil Nadu', district=?, address=?, postal_code=?,
                   approval_ref=?, demo=0 WHERE name=?""",
                (district, address, address.split()[-1], approval, name),
            )
        db.commit()


if __name__ == "__main__":
    main()
