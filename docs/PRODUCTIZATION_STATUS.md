# VerifyFlow productization status — 2026-10-25

This is a synthetic SIH prototype, not an official AICTE service or determination. The [feature audit](PRODUCTIZATION_AUDIT.md) maps existing modules and hardcoded configuration. This document records implemented changes and the current acceptance boundary.

## Implemented

- Five distinct officer roles: reviewer, compliance manager, second approver, administrator, and auditor. The second approver alone has `rules:publish`; a manager authors and submits. The administrator is limited to technical permissions. Rule simulation has a separate read-only permission. Existing user rows were preserved by migration `0013_second_approver` using `users.officer_role` for the fifth role, since the old SQLite check constraint accepts four roles.
- Authenticated portal transport using a configured shared secret and dedicated active reviewer account in a VerifyFlow regulatory workspace. Service credentials live in ignored `.env` files. `configure_local_integration.py` sets up the local pair and creates the service account without printing the credential.
- Immutable portal submission payloads, stable portal application and document-version IDs, per-version SHA-256 checks, duplicate-delivery detection, durable portal outbox with failure and retry history, and VerifyFlow receipt only after all declared documents are stored.
- Imported applications and document bytes use VerifyFlow's existing private storage, extraction jobs, audit chain, and review service. Portal resubmission versions map to the same VerifyFlow application. Applicant institution metadata and the portal form are stored in each submission snapshot; VerifyFlow's own `Institution` remains the regulatory tenant boundary.
- `manage.py sync` retries deliveries, triggers evidence analysis and rule validation after processing, routes new review findings to the least loaded active reviewer in the same regulatory workspace (excluding the service account), and pulls safe review status, assigned reviewer name, and active document requests back to the portal. Failed processing, absent rules, and evaluation errors are recorded separately from compliance failures. The portal does not move the initial submission to `received` until VerifyFlow acknowledges it. The routing switch is `VERIFYFLOW_PORTAL_AUTO_ASSIGN` (default true).
- Local SQLite databases were preserved. VerifyFlow migrations `0013`–`0015` were applied after a SQLite backup at `backend/var/backups/verifyflow-before-productization-20261025.db`. Portal schema initialization added `integration_outbox` without resetting existing records.

## Live synthetic acceptance evidence

Portal application `f8cbb7c7-26b8-44b2-a57d-faaf4b386b37` was submitted through the running Flask HTTP API and delivered with `py -3.11 manage.py sync`. VerifyFlow application `ed59286976354665a21c6b4d520cef9e` persisted submission version 1 and two mapped document versions. Both processing jobs succeeded, and validation run `61ec02ec50a64a3ba6769a5495c1de34` recorded `insufficient` for its one generic prototype rule. The portal outbox is `delivered` after one attempt and the institution-facing status reached `under_review`. These IDs are local synthetic records only.

A second live synthetic submission (`687fdc4e-152f-4eda-a4ad-a7840a880ad6`) verified the expanded workflow: VerifyFlow application `13231313910e47919e014441a52f11fd` has a persisted evidence analysis, validation run `7b1455da5af24458a5460450887759d9`, and an open review item assigned to an active reviewer. The portal reconciled to `under_review` and displayed the assigned reviewer's name.

## Rule and source status

The [official AICTE Approval Process Handbook 2024–2027](https://www.aicte.gov.in/sites/default/files/APH%20Final.pdf) references document lists for new institutions in Annexure 1 and extension applications in Annexure 2. The current portal's 12-category checklist and VerifyFlow's existing generic rule are **demo configuration**, not a verified copy of those annexures. No existing rule is labelled a verified official AICTE requirement. Later amendments and cycle-specific rules have not been reconciled. The synthetic factory in `mock-aicte-portal/synthetic_factory` has its own catalogue and source-status notes.

## Remaining work against the master brief

- The full AICTE rule catalogue, source verification states in the persisted rule schema, official category applicability, and governed document/field mapping migrations remain incomplete. Existing rule versioning and audit remain operational, but the present demonstration rule is generic.
- Portal form fields are retained in `portal_submissions.snapshot`; the deterministic rule engine does not yet evaluate those fields as typed inputs. The imported application workspace does not yet render the complete portal form and submission history.
- The evidence graph is generated from existing extraction and comparison records. It does not yet have explicit portal document-version nodes or edges for every imported field, nor a complete integrity test for all resubmission scenarios.
- Document requests synchronize from VerifyFlow review items to the portal. Final human decision, assignment summary, and all other status transitions do not yet synchronize bidirectionally. A portal resubmission is versioned and delivered but a full clarification–resubmission–revalidation live acceptance scenario remains to be run.
- The portal's historical audit table remains append-only through application code but is not hash-chained. VerifyFlow's audit chain is hash-chained and verifiable.
- The current reviewer routing policy only considers active reviewers in the same regulatory workspace and their count of active assigned items. Category-specific staffing, availability calendars, and conflict-of-interest rules remain unimplemented. Complete five-role negative testing, end-to-end acceptance A–H, and a green combined regression suite remain outstanding.

## Local run and verification

From `E:\sih 2` in PowerShell:

```powershell
cd '.\backend'
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
cd 'E:\sih 2\mock-aicte-portal'
py -3.11 manage.py init
py -3.11 -m app.web
```

In a third terminal, run `py -3.11 manage.py sync` periodically from the portal directory. For first-time local service setup, run `E:\sih 2\backend\.venv\Scripts\python.exe E:\sih 2\configure_local_integration.py` and restart both servers. The scripts preserve existing databases; do not use `manage.py reset` on data you need.

Run focused checks with `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_portal_intake.py backend\tests\test_rules_api.py`, `py -3.11 -m unittest discover -s mock-aicte-portal\tests -p test_workflow.py`, and `npm run typecheck` from `frontend`.
