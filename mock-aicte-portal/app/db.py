import os
import sqlite3
from pathlib import Path
from flask import g

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "var"
DB = DATA / "portal.sqlite3"
FILES = DATA / "uploads"

def connect():
    DATA.mkdir(exist_ok=True)
    FILES.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def get_db():
    if "db" not in g:
        g.db = connect()
    return g.db

def close_db(_error=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()

SCHEMA = """
CREATE TABLE IF NOT EXISTS institutions (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL, ownership TEXT NOT NULL,
 state TEXT NOT NULL, district TEXT NOT NULL, address TEXT NOT NULL, postal_code TEXT NOT NULL,
 contact_name TEXT NOT NULL, designation TEXT NOT NULL, email TEXT NOT NULL,
 phone TEXT NOT NULL, established_year INTEGER NOT NULL, approval_ref TEXT,
 demo INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users (
 id TEXT PRIMARY KEY, institution_id TEXT REFERENCES institutions(id), username TEXT NOT NULL UNIQUE,
 password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('institution','admin')),
 active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS categories (id TEXT PRIMARY KEY, name TEXT NOT NULL, config_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS requirements (id TEXT PRIMARY KEY, category_id TEXT NOT NULL REFERENCES categories(id),
 code TEXT NOT NULL, name TEXT NOT NULL, flag TEXT NOT NULL, condition_text TEXT,
 source TEXT NOT NULL, version TEXT NOT NULL, reviewed TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS applications (
 id TEXT PRIMARY KEY, institution_id TEXT NOT NULL REFERENCES institutions(id), category_id TEXT NOT NULL REFERENCES categories(id),
 reference TEXT UNIQUE, status TEXT NOT NULL, form_json TEXT NOT NULL DEFAULT '{}', declaration INTEGER NOT NULL DEFAULT 0,
 reviewer TEXT, decision TEXT, submitted_at TEXT, resubmitted_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_app_institution ON applications(institution_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_app_status ON applications(status);
CREATE TABLE IF NOT EXISTS documents (
 id TEXT PRIMARY KEY, application_id TEXT NOT NULL REFERENCES applications(id), code TEXT NOT NULL,
 current_version INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'uploaded',
 UNIQUE(application_id,code));
CREATE TABLE IF NOT EXISTS document_versions (
 id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id), version INTEGER NOT NULL,
 original_name TEXT NOT NULL, stored_name TEXT NOT NULL UNIQUE, mime TEXT NOT NULL, size INTEGER NOT NULL,
 uploaded_at TEXT NOT NULL, uploaded_by TEXT NOT NULL REFERENCES users(id), UNIQUE(document_id,version));
CREATE TABLE IF NOT EXISTS clarifications (
 id TEXT PRIMARY KEY, application_id TEXT NOT NULL REFERENCES applications(id), message TEXT NOT NULL,
 created_by TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL, resolved_at TEXT);
CREATE TABLE IF NOT EXISTS status_history (
 id TEXT PRIMARY KEY, application_id TEXT NOT NULL REFERENCES applications(id),
 from_status TEXT, to_status TEXT NOT NULL, note TEXT, actor_id TEXT NOT NULL REFERENCES users(id), at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_history_app ON status_history(application_id,at);
CREATE TABLE IF NOT EXISTS notifications (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), application_id TEXT REFERENCES applications(id),
 message TEXT NOT NULL, read_at TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit_log (
 id TEXT PRIMARY KEY, actor_id TEXT NOT NULL REFERENCES users(id), application_id TEXT REFERENCES applications(id),
 action TEXT NOT NULL, details TEXT, at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_audit_at ON audit_log(at);
CREATE TABLE IF NOT EXISTS sessions (
 id_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), csrf TEXT NOT NULL,
 expires_at TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS integration_outbox (
 id TEXT PRIMARY KEY, application_id TEXT NOT NULL REFERENCES applications(id),
 submission_version INTEGER NOT NULL, payload_json TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
 last_error TEXT, verifyflow_application_id TEXT, created_at TEXT NOT NULL, delivered_at TEXT,
 UNIQUE(application_id,submission_version));
CREATE INDEX IF NOT EXISTS idx_integration_outbox_state ON integration_outbox(state,created_at);
"""

def initialize():
    import json
    from .catalog import CATEGORIES, requirements
    db = connect()
    try:
        db.executescript(SCHEMA)
        if "verifyflow_stage" not in {column[1] for column in db.execute("PRAGMA table_info(applications)")}:
            db.execute("ALTER TABLE applications ADD COLUMN verifyflow_stage TEXT NOT NULL DEFAULT 'reviewer'")
        for c in CATEGORIES:
            db.execute("INSERT OR REPLACE INTO categories VALUES (?,?,?)", (c["id"], c["name"], json.dumps(c)))
            for r in requirements(c["id"]):
                db.execute("INSERT OR REPLACE INTO requirements VALUES (?,?,?,?,?,?,?,?,?)",
                           (r["id"], r["category_id"], r["code"], r["name"], r["flag"],r["condition"],r["source"],r["version"],r["reviewed"]))
    finally:
        db.close()
