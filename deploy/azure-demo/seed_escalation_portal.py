"""Create the Riverton walkthrough through the portal's real HTTP handlers.

This script is piped into `python -` inside the running portal container. Before
running, place three package PDFs in /app/var/seed-docs/riverton and a private
JSON file at /app/var/riverton-credentials.json with username and password.
Existing applications are left alone so a retry cannot create duplicates.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from app.db import connect
from app.web import app

DATA = Path("/app/var")
CREDS = json.loads((DATA / "riverton-credentials.json").read_text(encoding="utf-8"))
NAME = "Riverton Institute of Technology"


def expect(response, status: int):
    if response.status_code != status:
        raise RuntimeError(f"Portal returned {response.status_code}: {response.get_data(as_text=True)[:500]}")
    return response.get_json()


with app.test_client() as client:
    db = connect()
    try:
        existing = db.execute("SELECT id FROM institutions WHERE name=?", (NAME,)).fetchone()
    finally:
        db.close()
    if existing is None:
        expect(client.post("/api/auth/register", json={
            "name": NAME, "category": "Engineering & Technology", "ownership": "Private unaided",
            "state": "Tamil Nadu", "district": "Chennai", "address": "18 Knowledge Road, Chennai, Tamil Nadu",
            "postal_code": "600113", "contact_name": "Registrar", "designation": "Registrar",
            "email": "office@riverton.example.invalid", "phone": "9876504321", "established_year": "2024",
            "username": CREDS["username"], "password": CREDS["password"],
        }), 201)
    login = expect(client.post("/api/auth/login", json=CREDS), 200)
    csrf = login["data"]["csrf"]
    db = connect()
    try:
        existing_app = db.execute(
            "SELECT a.id,a.reference,a.status FROM applications a JOIN institutions i ON i.id=a.institution_id "
            "WHERE i.name=? AND a.category_id='new' ORDER BY a.created_at DESC LIMIT 1", (NAME,)
        ).fetchone()
    finally:
        db.close()
    if existing_app:
        print("Existing Riverton application:", tuple(existing_app))
    else:
        app_id = expect(client.post("/api/applications", json={"category_id": "new", "csrf": csrf}), 201)["data"]["id"]
        expect(client.patch(f"/api/applications/{app_id}", json={
            "csrf": csrf, "programme": "Computer Science and Engineering", "level": "Undergraduate",
            "proposed_intake": "60", "academic_year": "2026-27",
            "justification": "Proposal for a new technical institution, supported by the enclosed records.",
            "declaration": 1,
        }), 200)
        for code in ("registration", "programme", "declaration"):
            path = DATA / "seed-docs" / "riverton" / f"{code}.pdf"
            pdf = path.read_bytes()
            expect(client.post(f"/api/applications/{app_id}/documents", data={
                "csrf": csrf, "code": code, "file": (io.BytesIO(pdf), path.name, "application/pdf"),
            }, content_type="multipart/form-data"), 201)
        expect(client.post(f"/api/applications/{app_id}/submit", json={"csrf": csrf}), 200)
        db = connect()
        try:
            result = db.execute("SELECT reference,status FROM applications WHERE id=?", (app_id,)).fetchone()
            print("Created Riverton application:", app_id, tuple(result), "with 3 documents")
        finally:
            db.close()
