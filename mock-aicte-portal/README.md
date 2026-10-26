# EduApproval — Institutional Application Portal

For the separate 14-category synthetic document factory and its generated PDF dataset, see [SYNTHETIC_FACTORY.md](SYNTHETIC_FACTORY.md).

**SIH PROTOTYPE — NOT AN OFFICIAL AICTE PORTAL.** This fictional institution portal can send synthetic applications to the adjacent VerifyFlow AI service when local integration is configured. It does not connect to AICTE or any official submission service.

## Location and architecture

This project lives in `mock-aicte-portal` alongside VerifyFlow AI. Its database and uploads remain separate; the authenticated intake API transfers versioned copies to VerifyFlow.

| Path | Purpose |
| --- | --- |
| `app/catalog.py` | Twelve configurable prototype categories, fields, and document checklists |
| `app/db.py` | SQLite schema and repeatable schema initialization |
| `app/services.py` | Validation, authorization-aware application services, file handling, transitions |
| `app/web.py` | Flask routes and server-side pages |
| `app/templates/`, `app/static/` | Responsive interface |
| `manage.py` | Local database setup, deterministic demo seed, explicit reset |
| `app/integration.py` | Durable submission outbox, retry and status reconciliation |
| `tests/` | Automated workflow and access tests |
| `var/` | Local SQLite database and private uploads; ignored by Git |

SQLite was chosen because this prototype runs locally without a separate database service. `python manage.py init` creates the schema using `CREATE TABLE IF NOT EXISTS` and upserts the catalogue. The schema has foreign keys, uniqueness constraints, indexes, and stable UUID primary keys. A future schema change should add a numbered migration before changing deployed demo data.

The UI follows the adjacent VerifyFlow AI project's visual vocabulary: midnight canvas, tricolor and violet accents, floating glass navigation, layered cards, short entrance transitions, pointer-responsive highlights, and reduced-motion support. The theme is implemented locally in `app/static/verifyflow-theme.css` and `app/static/portal.js`.

## Windows PowerShell setup

Run these commands from this directory:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` and replace `SECRET_KEY` with a long random local secret. For example:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Then initialize, seed, and run:

```powershell
python manage.py init
python manage.py seed
python -m app.web
```

When `VERIFYFLOW_INTAKE_URL` and `VERIFYFLOW_INTAKE_SECRET` are set in `.env`, the portal server automatically sends submitted documents to VerifyFlow and refreshes reviewer status. A failed delivery remains in the outbox for retry. `python manage.py sync` can also trigger delivery and reconciliation manually.

VerifyFlow treats the portal's document codes as institutional evidence. Its configurable extractor reads labelled fields and adjacent table cells for institution identity, references, programme, intake, affiliation and capacity. Cross-document comparison can flag inconsistent values for officer review. General identity fields such as date of birth are not applied to these portal documents. Portal regulatory rules must be explicitly published in VerifyFlow under the `aicte` or `portal` rule category; no official AICTE rule set is bundled with this prototype.

Open [http://127.0.0.1:5000](http://127.0.0.1:5000). The server binds to localhost by default. The `.env` file is loaded by the web app. `PORT`, `MAX_UPLOAD_MB`, and `MAX_VERSIONS_PER_DOCUMENT` are configurable there. The seed command uses the default 8 MB file limit and writes small PDFs.

Run tests:

```powershell
python -m unittest discover -s tests -v
```

Reset **only this portal's local demo database and uploaded files** and recreate the seed:

```powershell
python manage.py reset
```

`reset` removes `var/portal.sqlite3` and `var/uploads`; it deletes any accounts and files created in this local portal. `seed` alone is idempotent and leaves existing demo records unchanged.

## Demo access

| Role | Username | Password |
| --- | --- | --- |
| Portal administrator | `demo_admin` | `DemoAdmin!2026` |
| Draft institution | `aster_demo` | `DemoInstitute!2026` |
| Submitted institution | `cedar_demo` | `DemoInstitute!2026` |
| Under review institution | `meridian_demo` | `DemoInstitute!2026` |
| Clarification institution | `bluehaven_demo` | `DemoInstitute!2026` |
| Resubmitted institution | `northstar_demo` | `DemoInstitute!2026` |
| Decision institution | `silverleaf_demo` | `DemoInstitute!2026` |

All seed data is fictional. Emails use `example.invalid`, contact phone numbers are synthetic, and PDFs visibly state **SYNTHETIC — DEMO ONLY — NOT AN OFFICIAL DOCUMENT**. The Bluehaven programme PDF deliberately lists an intake different from its application form for future validation experiments.

## Implemented workflow

- Institution registration, sign-in and sign-out; server-side hashed passwords; expiring database sessions and CSRF tokens; role and institution ownership checks.
- Profile editing; twelve category-led draft forms; local persistence; required-field, declaration, and required-document validation on submission. Each application page has an explicit upload form and a Save and submit button.
- Protected PDF, PNG and JPEG upload/download; extension, MIME and signature checks; size and version limits; random server filenames; metadata and version history. Files are outside public static paths.
- Unique reference on submission; status history, notifications, clarifications, resubmission, demo reviewer assignment, decision recording, account access controls, and audit events.
- Institution dashboard, search and status filtering, detail tracking; separate admin queue, directory, review controls, and audit log.
- Six deterministic sample institutions spanning draft through decision recorded. Running `seed` repeatedly does not duplicate them.

The internal JSON APIs use `/api/` routes. Authenticated mutations require the CSRF token returned by `/api/auth/login` in `X-CSRF-Token` or the JSON body. The interface uses the same protected services. Examples include `/api/application-categories`, `/api/applications`, `/api/applications/<id>/submit`, `/api/applications/<id>/resubmit`, and `/api/admin/applications/<id>/action`.

## Prototype rule status and limits

The [official AICTE Approval Process Handbook 2024–2027](https://aicte-qa.aicte-india.org/sites/default/files/APH%20Final.pdf) was consulted for broad workflow context. The catalogue deliberately **does not claim** that its category list, fields, eligibility notes, or document flags are official or current AICTE rules. Every checklist item is labelled **“Demo requirement — verification pending”** with a prototype version and review date. Official amendments and category-specific requirements would need a separate verified rule-mapping exercise before any production use.

This remains a local prototype: no email delivery or password-reset service, payments, official approval decision, or production deployment controls are provided. The local VerifyFlow integration uses an authenticated intake API; it does not connect to AICTE. File previews use authorized download rather than inline rendering. The admin queue is capped at 200 rows in this phase.

For a later phase, structured application fields, references, document metadata, submission timestamps, and status history are separable from private file content. Any data-sharing adapter would need an explicit contract and authorization design before implementation.
