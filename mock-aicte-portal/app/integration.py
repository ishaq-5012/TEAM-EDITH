"""Durable portal-to-VerifyFlow delivery, retries, and review status updates."""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import secrets

from werkzeug.security import generate_password_hash

from . import db as portal_db
from .services import audit, now, row, rows, status_change, uid


def integration_actor(db) -> str:
    """An inactive technical identity makes imported actions distinguishable in audit history."""
    service = row(db, "SELECT id FROM users WHERE username='verifyflow_sync'")
    if service:
        return service["id"]
    actor_id = uid()
    db.execute("INSERT INTO users VALUES (?,?,?,?,?,?,?)",
               (actor_id, None, "verifyflow_sync", generate_password_hash(secrets.token_urlsafe(48)),
                "admin", 0, now()))
    return actor_id


def queue_submission(db, application_id: str, actor_id: str) -> int:
    app = row(db, "SELECT * FROM applications WHERE id=?", (application_id,))
    inst = row(db, "SELECT * FROM institutions WHERE id=?", (app["institution_id"],))
    category = row(db, "SELECT name FROM categories WHERE id=?", (app["category_id"],))
    versions = rows(db, """SELECT d.id document_id,d.code,v.id version_id,v.version,v.original_name filename,
        v.stored_name,v.mime FROM documents d JOIN document_versions v
        ON v.document_id=d.id AND v.version=d.current_version
        WHERE d.application_id=? AND d.status='uploaded' ORDER BY d.code""", (application_id,))
    documents = []
    for v in versions:
        path = portal_db.FILES / v["stored_name"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        documents.append({"document_id": v["document_id"], "code": v["code"],
                          "version_id": v["version_id"], "version": v["version"],
                          "filename": v["filename"], "mime": v["mime"], "sha256": digest})
    next_version = db.execute("SELECT coalesce(max(submission_version),0)+1 FROM integration_outbox WHERE application_id=?", (application_id,)).fetchone()[0]
    payload = {"portal_application_id": application_id, "submission_version": next_version,
               "reference": app["reference"], "category_id": app["category_id"],
               "category_name": category["name"],
               "institution": {k: inst[k] for k in ("id", "name", "category", "ownership", "state", "district", "address", "postal_code", "approval_ref")},
               "form": json.loads(app["form_json"]),
               "submitted_at": app["resubmitted_at"] or app["submitted_at"],
               "documents": documents}
    db.execute("INSERT INTO integration_outbox (id,application_id,submission_version,payload_json,created_at) VALUES (?,?,?,?,?)",
               (uid(), application_id, next_version, json.dumps(payload, sort_keys=True), now()))
    audit(db, actor_id, "integration:queued", application_id, f"submission v{next_version}")
    return next_version


def _call(base: str, secret: str, method: str, path: str, data: bytes | None = None, content_type: str = "application/json") -> dict:
    request = urllib.request.Request(base.rstrip("/") + path, data=data, method=method,
        headers={"X-Portal-Secret": secret, "Content-Type": content_type})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def deliver_one(db, outbox_id: str) -> bool:
    base = os.environ.get("VERIFYFLOW_INTAKE_URL", "").rstrip("/")
    secret = os.environ.get("VERIFYFLOW_INTAKE_SECRET", "")
    if not base or not secret:
        raise RuntimeError("Set VERIFYFLOW_INTAKE_URL and VERIFYFLOW_INTAKE_SECRET")
    item = row(db, "SELECT * FROM integration_outbox WHERE id=?", (outbox_id,))
    if not item or item["state"] == "delivered":
        return True
    payload = json.loads(item["payload_json"])
    prefix = "/api/v1/portal-intake/submissions"
    suffix = "/" + urllib.parse.quote(item["application_id"], safe="") + "/" + str(item["submission_version"])
    db.execute("UPDATE integration_outbox SET attempts=attempts+1,state='delivering' WHERE id=?", (outbox_id,))
    try:
        receipt = _call(base, secret, "POST", prefix, json.dumps(payload).encode())
        for d in payload["documents"]:
            version = row(db, "SELECT stored_name FROM document_versions WHERE id=?", (d["version_id"],))
            if version is None:
                raise RuntimeError("Document version missing from local database")
            content = (portal_db.FILES / version["stored_name"]).read_bytes()
            if hashlib.sha256(content).hexdigest() != d["sha256"]:
                raise RuntimeError("Document changed after submission; delivery halted")
            _call(base, secret, "PUT", prefix + suffix + "/documents/" + urllib.parse.quote(d["version_id"], safe=""), content, d["mime"])
        completed = _call(base, secret, "POST", prefix + suffix + "/complete", b"{}")
        if completed.get("state") != "received":
            raise RuntimeError("VerifyFlow did not acknowledge receipt")
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute("UPDATE integration_outbox SET state='delivered',last_error=NULL,verifyflow_application_id=?,delivered_at=? WHERE id=?",
                       (receipt["application_id"], now(), outbox_id))
            app = row(db, "SELECT * FROM applications WHERE id=?", (item["application_id"],))
            actor = integration_actor(db)
            if app["status"] in ("submitted", "resubmission_pending"):
                status_change(db, app, "received" if app["status"] == "submitted" else "resubmission_received",
                              actor, "VerifyFlow confirmed persisted submission")
            audit(db, actor, "integration:delivered", app["id"], f"submission v{item['submission_version']} -> {receipt['application_id']}")
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
        return True
    except (OSError, urllib.error.HTTPError, ValueError, KeyError, RuntimeError) as exc:
        detail = str(exc)[:300]
        db.execute("UPDATE integration_outbox SET state='failed',last_error=? WHERE id=?", (detail, outbox_id))
        actor = integration_actor(db)
        audit(db, actor, "integration:failed", item["application_id"], detail)
        return False


def deliver_pending(db, limit: int = 50) -> tuple[int, int]:
    pending = rows(db, "SELECT id FROM integration_outbox WHERE state IN ('pending','failed','delivering') ORDER BY created_at LIMIT ?", (limit,))
    successes = sum(deliver_one(db, item["id"]) for item in pending)
    return successes, len(pending) - successes


def reconcile_status(db, limit: int = 50) -> tuple[int, int]:
    """Pull safe review status and active document requests for delivered submissions."""
    base = os.environ.get("VERIFYFLOW_INTAKE_URL", "").rstrip("/")
    secret = os.environ.get("VERIFYFLOW_INTAKE_SECRET", "")
    if not base or not secret:
        raise RuntimeError("Set VERIFYFLOW_INTAKE_URL and VERIFYFLOW_INTAKE_SECRET")
    items = rows(db, """SELECT o.* FROM integration_outbox o JOIN
        (SELECT application_id,max(submission_version) version FROM integration_outbox
         WHERE state='delivered' GROUP BY application_id) latest
        ON o.application_id=latest.application_id AND o.submission_version=latest.version
        ORDER BY o.delivered_at DESC LIMIT ?""", (limit,))
    updated = failed = 0
    for item in items:
        path = "/api/v1/portal-intake/submissions/" + urllib.parse.quote(item["application_id"], safe="") + "/" + str(item["submission_version"])
        try:
            _call(base, secret, "POST", path + "/evaluate", b"{}")
            data = _call(base, secret, "GET", path)
            db.execute("BEGIN IMMEDIATE")
            try:
                app = row(db, "SELECT * FROM applications WHERE id=?", (item["application_id"],))
                actor = integration_actor(db)
                assignee = data.get("assigned_reviewer")
                stage = data.get("review_stage", "reviewer")
                if stage in ("reviewer", "audit", "approved") and stage != app["verifyflow_stage"]:
                    db.execute("UPDATE applications SET verifyflow_stage=?,updated_at=? WHERE id=?", (stage, now(), app["id"]))
                    audit(db, actor, "integration:review_stage", app["id"], stage)
                    updated += 1
                if assignee and assignee != app["reviewer"]:
                    db.execute("UPDATE applications SET reviewer=?,updated_at=? WHERE id=?", (assignee[:80], now(), app["id"]))
                    audit(db, actor, "integration:reviewer_assigned", app["id"], assignee[:80])
                    updated += 1
                if data["application_status"] in ("processing", "needs_review") and app["status"] in ("received", "resubmission_received"):
                    status_change(db, app, "under_review", actor, "VerifyFlow processing or review in progress")
                    app = row(db, "SELECT * FROM applications WHERE id=?", (item["application_id"],))
                    updated += 1
                if stage == "approved" and app["status"] in ("received", "resubmission_received"):
                    status_change(db, app, "under_review", actor, "VerifyFlow review completed")
                    app = row(db, "SELECT * FROM applications WHERE id=?", (item["application_id"],))
                if stage == "approved" and app["status"] == "under_review":
                    status_change(db, app, "decision_recorded", actor, "VerifyFlow auditor approved verification")
                    db.execute("UPDATE applications SET decision=? WHERE id=?",
                               ("Document verification approved by VerifyFlow auditor; external regulatory approval is separate.", app["id"]))
                    updated += 1
                for request in data.get("document_requests", []):
                    if not row(db, "SELECT id FROM clarifications WHERE id=?", (request["id"],)):
                        db.execute("INSERT INTO clarifications VALUES (?,?,?,?,?,?)",
                                   (request["id"], app["id"], request["description"], actor, now(), None))
                        if app["status"] in ("received", "under_review", "resubmission_received"):
                            status_change(db, app, "clarification_required", actor, "VerifyFlow requested supporting evidence")
                            app = row(db, "SELECT * FROM applications WHERE id=?", (item["application_id"],))
                        for user in rows(db, "SELECT id FROM users WHERE institution_id=? AND active=1", (app["institution_id"],)):
                            from .services import notify
                            notify(db, user["id"], app["id"], "Clarification requested: " + request["description"][:120])
                        audit(db, actor, "integration:clarification", app["id"], request["id"])
                        updated += 1
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        except (OSError, ValueError, KeyError, RuntimeError) as exc:
            failed += 1
            actor = integration_actor(db)
            audit(db, actor, "integration:reconcile_failed", item["application_id"], str(exc)[:300])
    return updated, failed
