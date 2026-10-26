"""Optional local smoke: submit synthetic files through both running HTTP services.

Requires seeded portal demo users and configured integration. Creates one demo application.
"""

from __future__ import annotations

import json
import os

import httpx
import pymupdf

INSTITUTION_PASSWORD = "DemoInstitute!2026"  # seeded synthetic account only


def pdf(marker: str) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "SYNTHETIC TEST DOCUMENT — " + marker)
    out = doc.tobytes()
    doc.close()
    return out


def main() -> None:
    base = os.environ.get("PORTAL_SMOKE_URL", "http://127.0.0.1:5000")
    with httpx.Client(base_url=base, timeout=20) as client:
        login = client.post("/api/auth/login", json={"username": "aster_demo", "password": INSTITUTION_PASSWORD})
        login.raise_for_status()
        csrf = login.json()["data"]["csrf"]
        headers = {"X-CSRF-Token": csrf}
        created = client.post("/api/applications", json={"category_id": "other"}, headers=headers)
        created.raise_for_status()
        app_id = created.json()["data"]["id"]
        saved = client.patch(f"/api/applications/{app_id}", json={"programme": "Synthetic Robotics",
            "academic_year": "2026-27", "justification": "Synthetic end-to-end intake test",
            "declaration": 1}, headers=headers)
        saved.raise_for_status()
        for code in ("explanation", "declaration"):
            uploaded = client.post(f"/api/applications/{app_id}/documents", headers=headers,
                data={"code": code}, files={"file": (code + ".pdf", pdf(code), "application/pdf")})
            uploaded.raise_for_status()
        submitted = client.post(f"/api/applications/{app_id}/submit", headers=headers)
        submitted.raise_for_status()
        print(json.dumps({"portal_application_id": app_id, "status": "submitted"}))


if __name__ == "__main__":
    main()
