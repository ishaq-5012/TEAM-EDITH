# VerifyFlow AI

Enterprise application validation, document authentication and regulatory compliance verification — built as an
**evidence-assistance system**. VerifyFlow never claims a document is authentic, a signature is trusted, or a
regulation was violated without supporting evidence. Missing evidence and claims it can't establish are reported
as outcomes in their own right.

> **Status: Phase 13 — deployment preparation.** Production configuration, container files, a durable processing
> worker, readiness checks, backup/restore and smoke-test scripts, and dependency upgrades that clear all known
> production advisories. The backend suite passes on SQLite and PostgreSQL 16. **Not deployed, and not yet verified on
> real infrastructure**; see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for what was and wasn't tested.
>
> Phase 12 (integration, hardening and acceptance): An end-to-end synthetic workflow test drives all 13
> steps through the public API, and new tests cover security boundaries, provider outages, concurrency, fresh-database
> migrations and reduced motion. The results, the innovation-by-innovation audit and the remaining risks are in
> [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md); the system design is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
>
> Phase 11 (design system, accessibility and motion): One enterprise design system across all seven
> modules, keyboard and screen-reader support throughout, purposeful motion that respects reduced-motion settings,
> and a responsive layout checked at phone, tablet and desktop widths. No business logic changed. See
> [Design system, accessibility and motion (Phase 11)](#design-system-accessibility-and-motion-phase-11).
>
> Phase 10 (Command Center and Governance & Insights):
> - a Command Center and a Governance & Insights module built only from database aggregates over stored records, with
>   a documented definition, time basis and data source for every metric (`GET /insights/definitions`)
> - application volume and processing, findings by outcome and severity, review backlog and workload, extraction
>   quality, uncertainty and insufficient-evidence rates, and engine failures kept separate from human-confirmed ones
> - rule-version usage, validation history, rule governance history with the four-eyes check, and false-positive
>   rates from reviewer decisions
> - no double counting across repeated validation runs, and current state kept apart from windowed history
> - audit history filters (action group, outcome, dates, text) and role-restricted, audited CSV/JSON exports; document
>   values only with a separate permission, an explicit opt-in and a recorded reason
> - labelled synthetic demo data (`seed-demo`, development only) that can be excluded from every metric
>
> Phase 9 (AI assistance):
> - a provider-independent AI layer with a safe no-AI mode (the default) and a Claude adapter on the official
>   Anthropic SDK; the API key stays on the backend
> - one guarded call path: input caps, per-process and per-user rate limits, a daily spend budget, timeouts, bounded
>   retries, strict output schemas, and safe handling of invalid JSON, empty output and refusals
> - explicit control over which document content may leave the environment (none / extracted values / page text),
>   with identifier masking and a stored manifest of what was sent
> - plain-language explanations of rule results and evidence findings, where every statement cites stored records
>   that are verified against the database; document-type and field-value suggestions that are never applied
> - prompt-injection defences: document text is framed as data, the model has no tools, and authenticity, decision
>   and override claims are filtered out
> - an explanation panel with the authoritative deterministic result, evidence links, provider state and limitations,
>   falling back to deterministic explanations when AI is off or fails
>
> Phase 8 (Trust and Authentication Center): SHA-256 integrity re-checks, PDF signature validation with pyHanko,
> certificate trust only against configured anchors, offline/online revocation, timestamps and registry connectors,
> with immutable verification history. See `app/trust/` and the Trust module.
>
> Phase 7 (Review and Resolution Center):
> - a review queue, fed by validation runs, with failure / uncertain / missing-evidence categories and filters
> - assignment, comments, escalation, document requests, and confirm / dismiss / reopen decisions with required
>   reasons
> - corrections from the review screen that keep the original extraction, record before/after values, and
>   automatically revalidate when a rule in force reads the field; validation runs are linked to their predecessor
> - optimistic locking and idempotent requests against conflicting or duplicate decisions; append-only, audited
>   history
> - a split-pane review screen: original document with the value highlighted, extracted field, comparison
>   evidence, applicable rule, uncertainty reasons and prior history
>
> Phase 6 (Compliance Studio):
> - a declarative rule engine: JSON rules with allowlisted operators only, no user-supplied code or expressions
> - immutable, effective-dated rule versions with draft → pending approval → published → retired states and
>   four-eyes approval
> - missing-data and low-confidence policies, configurable severity and outcomes
> - synthetic test cases that gate submission, version comparison, and a read-only before/after what-if simulator
> - reproducible validation runs that store the exact rule versions and input snapshot, with rule-to-evidence traces
> - a rule editor with a structured condition builder, JSON view and live server-side validation
>
> A passing rule is **not** a legal or regulatory determination. Each rule documents its source, owner and approval
> status.
>
> Phase 5 (Evidence Intelligence Graph):
> - deterministic cross-document comparison of names, dates, identifiers, addresses, document numbers and
>   configurable fields
> - separate outcome, evidence-quality and severity dimensions
> - fully traceable findings and explanations generated from stored evidence
> - documented priority factors
> - reproducible, immutable analyses
> - an interactive evidence graph with an accessible list view
>
> Phase 4 (extraction):
> - per-page text from the PDF text layer, or OCR for scanned or garbled pages, with explicit OCR-unavailable,
>   low-quality and failed states
> - configurable field definitions with field-specific normalization into strict schemas
> - raw and normalized values with page coordinates, extraction runs that are idempotent and safe under concurrent
>   processing, and append-only human corrections
> - the Extraction Inspector, with page rendering and coordinate highlighting
>
> Built on Phase 3:
> - applications with filtering, pagination, ownership, members and a full lifecycle
> - secure document upload: content-verified type, size and structure limits, SHA-256 hashing, private storage
> - automatic intake inspection, with retry when it fails
> - authorized, integrity-checked download and in-app preview
> - a drag-and-drop UI with real upload progress
>
> These run on the Phase 1–2 platform: cookie sessions with CSRF protection, four roles enforced by the backend,
> and the hash-chained audit trail.

## Repository layout

```
backend/                 FastAPI modular monolith (Python 3.11+)
  app/core/              settings + env validation, logging/redaction, security, RBAC (roles), ownership (authz)
  app/db/                SQLAlchemy base (UTC-aware timestamps), engine/session
  app/models/            ORM models (users, sessions, login attempts, applications, members, documents,
                         processing jobs, audit events + chain head)
  app/schemas/           Pydantic request/response contracts
  app/services/          auth, sessions, users, applications, documents (upload pipeline), processing
                         (intake inspection), hash-chained audit, private storage, capabilities, demo files
  app/integrations/ai/   AI provider protocol, registry, Disabled (no-AI) and Anthropic providers, guarded gateway
  app/assist/            AI egress policy and data framing, strict output schemas, content guard, prompts
  app/api/               routers, session/CSRF/permission dependencies, cookie helpers
  app/cli.py             operator commands: bootstrap-dev-admin, create-user, make-demo-files, seed-demo,
                         verify-audit
  app/insights/          metric definitions (what, when, where from, de-duplication)
  alembic/               reviewed migrations
  tests/                 pytest + HTTPX
  requirements.txt       runtime dependencies (pinned)
  requirements-dev.txt   + pytest, httpx, ruff
  .env.example           every supported environment variable
frontend/                React 18 + TypeScript + Vite 6
  src/lib/               typed API client; contracts mirroring backend schemas
  src/components/ui/     design system: Button, Card, Field, Dialog, StatusPill, states (loading/empty/error)
  src/components/layout/ AppShell, Sidebar, Topbar, Breadcrumbs, PageContainer, module registry
  src/features/          auth, applications (list, workspace, upload, inventory, preview), command-center,
                         governance, account, modules, ai (explanation panel, document suggestions, status card)
  .env.example           dev-server proxy target
docs/API.md              endpoint reference
docs/ARCHITECTURE.md     layers, modules, data flow, immutability and determinism boundaries
docs/ACCEPTANCE.md       Phase 12 acceptance checklist, innovation audit, command results and remaining risks
docs/DEPLOYMENT.md       production deployment, secrets, migrations, backups, retention, rollback, smoke checklists
deploy/                  production env template, docker-compose, nginx, backup/restore and smoke-test scripts
```

## Prerequisites (Windows)

| Tool | Version used | Check |
|---|---|---|
| Python | 3.11.9 | `python --version` |
| Node.js | 20+ (tested on 25.2.1) | `node --version` |
| npm | 10+ (tested on 11.6.2) | `npm --version` |
| Tesseract OCR | optional | detected at runtime; OCR shows as unavailable without it |

## Setup — Windows PowerShell

Run from the repository root (for example `E:\sih 2`). Quote paths that contain spaces.

A virtual environment is tied to the Python installation that created it. If you copy or move the project to another
machine or drive, delete `backend\.venv` and create it again (step 1), then update any absolute paths in
`backend\.env` and `.claude\launch.json`.

### 1. Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env          # optional: defaults work for local development
.\.venv\Scripts\python.exe -m alembic upgrade head
```

#### Create the first administrator

There is no default account, no hardcoded password and no self-registration. Choose one of the two options below.

**Option A: development only (`bootstrap-dev-admin`).** Use this for a local development database.

```powershell
.\.venv\Scripts\python.exe -m app.cli bootstrap-dev-admin --email you@example.com --name "Your Name"
```

- It generates a random, policy-compliant password and prints it **once**. The password isn't written to any file,
  log or the audit trail (only its Argon2id hash is stored).
- Change it after your first sign-in from **Account → Change password**.
- It refuses to run unless `VERIFYFLOW_ENVIRONMENT=development` (the default in `.env.example`).
- It refuses to run once any user exists, so it can't become a backdoor on a populated system.
- It's recorded in the audit log as `user.bootstrap_admin`.
- Treat the terminal output as a secret: don't paste it into tickets or chat. If it was exposed, change the password
  right away.

**Option B: any environment, including production (`create-user`).** You choose the password at an interactive,
non-echoing prompt. It must be at least 12 characters and mix at least three of lowercase, uppercase, digits and
symbols.

```powershell
.\.venv\Scripts\python.exe -m app.cli create-user --email you@yourorg.com --name "Your Name" --role admin
```

For unattended provisioning, set `VERIFYFLOW_BOOTSTRAP_PASSWORD` from your secret manager for that single command,
then clear it. Never put it in `.env` or a script.

Further accounts are created by an administrator in **Governance → Users & roles**.

#### Synthetic sample documents (optional)

```powershell
.\.venv\Scripts\python.exe -m app.cli make-demo-files
```

This writes clearly-labelled synthetic files to `backend\var\demo-files` (git-ignored). They're for trying the
upload pipeline: valid PDFs and PNGs, a scanned PDF without a text layer, a PDF with a JavaScript action
(→ needs review), and two files that must be rejected (a PNG renamed `.pdf`, and text named `.pdf`). None of them
contain real data.

#### Synthetic demo applications (optional, development only)

```powershell
.\.venv\Scripts\python.exe -m app.cli seed-demo --owner-email you@example.com
```

Creates three applications titled `[SYNTHETIC DEMO] …`, flagged `is_synthetic`, with fictional documents, and runs them
through the real pipeline (extraction, evidence analysis, and validation if you have published rules). The dashboards
then show what the pipeline actually produced. Synthetic applications are labelled everywhere and can be excluded
from insights. The command refuses to run in production.

Start the API (leave this window open):

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Check health from a second PowerShell window:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
```

Expected: `status: ok`, `database: ok`. OpenAPI docs: <http://127.0.0.1:8000/api/docs>.

### 2. Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173> and sign in. The dev server proxies `/api` to `http://127.0.0.1:8000`, so the
browser sees one origin, and the session cookies are first-party and `SameSite`-protected. To change the target,
copy `.env.example` to `.env.local` and set `VERIFYFLOW_API_PROXY_TARGET`.

> Session cookies are `Secure`. Browsers accept them on `http://localhost` and `http://127.0.0.1`. If you serve
> the frontend over plain HTTP on any other hostname, sign-in will appear to succeed but the cookie will be dropped.
> Use HTTPS, or for local testing only, set `VERIFYFLOW_COOKIE_SECURE=false`.

> If PowerShell blocks `npm` with an execution-policy error, run `npm.cmd install` / `npm.cmd run dev`, or run
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

## Quality checks — Windows PowerShell

```powershell
# Backend (from backend\)
.\.venv\Scripts\python.exe -m pytest
# The same suite on PostgreSQL (a disposable server you may create/drop databases on):
$env:VERIFYFLOW_TEST_POSTGRES_URL = "postgresql+psycopg://postgres@127.0.0.1:5432/postgres"; .\.venv\Scripts\python.exe -m pytest; Remove-Item Env:VERIFYFLOW_TEST_POSTGRES_URL
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m alembic check        # models and migrations in sync

# Frontend (from frontend\)
npm run typecheck
npm run lint
npm test
npm run build
```

Each backend test runs against a fresh database built by the real Alembic migrations, so the migrations are
exercised on every run. The suite also uses HTTPX's async client against the ASGI app.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `did not find executable at 'C:\Users\…\python.exe'` when starting the API | `backend\.venv` was created on another machine or Python install | `Remove-Item -Recurse -Force .venv`, then repeat backend setup step 1 |
| `ModuleNotFoundError: No module named 'httpx'` at startup | Installed from an older `requirements.txt` (httpx was only a dev dependency before Phase 12) | Run `pip install -r requirements.txt` again |
| Trust checks find no trust anchors, or startup rejects `VERIFYFLOW_TRUST_ROOTS_DIR` | `backend\.env` points to a folder on another drive | Set it to an existing folder, for example `E:/sih 2/backend/var/trust-fixtures/trust-roots`, or leave it empty |
| Sign-in shows "Request failed (HTTP 500)" | The API isn't running, or crashed at import, so the dev proxy fails | Check the API window. `Invoke-RestMethod http://127.0.0.1:8000/api/v1/health` should return `status: ok` |
| Sign-in appears to work, then you're signed out at once | `Secure` cookies are dropped over plain HTTP on a host other than localhost | Use HTTPS or `http://localhost`, or (local only) `VERIFYFLOW_COOKIE_SECURE=false` |
| `403 origin_rejected` | The page's origin isn't in `VERIFYFLOW_CORS_ORIGINS` and isn't the API's own origin | Use the Vite proxy (one origin), or add the exact origin |
| `403 csrf_failed` | The request didn't carry this session's `X-CSRF-Token` (for example, a hand-made request, or a token from another session) | Use the token returned by `/auth/login` or `/auth/me`; the SPA sends it automatically |
| OCR shows "unavailable" for scanned pages | Tesseract isn't installed, or `VERIFYFLOW_TESSERACT_CMD` is wrong | `winget install --id UB-Mannheim.TesseractOCR`, then set `VERIFYFLOW_TESSERACT_CMD=C:/Program Files/Tesseract-OCR/tesseract.exe` in `backend\.env`, restart the API and reprocess scanned documents |
| `database is locked` under heavy local load | SQLite allows one writer at a time | Expected in development; use PostgreSQL for concurrent load |
| A few frontend tests time out on a busy machine | `findBy` waits (3 s) run out when dev servers and browsers compete for CPU | Stop the dev servers, or run `npx vitest run --maxWorkers=3` |
| `npm` is blocked by the execution policy | PowerShell script policy | Use `npm.cmd`, or run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once |
| `alembic check` reports changes | A model was edited without a migration | Write and review a migration; `tests/test_security_boundaries.py` also fails on any drift |

## Configuration

All backend settings are environment variables prefixed `VERIFYFLOW_`. They can also go in `backend\.env`, and
`backend\.env.example` lists every one. They're validated at startup, and invalid values stop the server with a
readable message such as:

```
app.core.config.ConfigError: Invalid VerifyFlow configuration:
  - VERIFYFLOW_CORS_ORIGINS: wildcard '*' is not allowed; list explicit origins
```

Validated rules include:
- The database URL scheme must be SQLite or PostgreSQL.
- CORS origins must be explicit (no `*`, no paths).
- Log level and log format must be known values.
- Session lifetimes and throttling limits must be within bounds.
- The AI provider name must be well-formed.
- A configured Tesseract path must exist.
- The storage directory must be outside the frontend tree.
- In production: SQLite is rejected, CORS origins must use HTTPS, and `VERIFYFLOW_COOKIE_SECURE` must be true.

## Observability and error handling

- **Request IDs:** every response carries `X-Request-ID`. A well-formed incoming ID (8–64 characters,
  `[A-Za-z0-9-]`) is reused; otherwise one is generated. The ID appears on every log line and audit event for that
  request.
- **Access log:** one line per request with method, path, status, duration and client IP. The path is logged without
  its query string.
- **Redaction:** a logging filter removes passwords, tokens, secrets, API keys, cookies, `Authorization` / Bearer
  values and JWTs from log messages, arguments, structured fields and exception text before anything is written.
- **Errors:** every error uses `{"error": {"code", "message", "details"}}`. Unhandled exceptions are logged with a
  stack trace and returned as a generic `internal_error`, so no internals leak to the client.
- **Format:** `VERIFYFLOW_LOG_FORMAT=json` emits one JSON object per line for log shippers.

## Authentication and authorization

**Sessions.** Signing in creates a server-side session.
- The browser receives a random 256-bit token in an `HttpOnly; Secure; SameSite=Lax` cookie with the `__Host-`
  prefix. Page scripts can never read it, and the server stores only its SHA-256 hash.
- Sessions end after 30 minutes idle or 12 hours total (both configurable).
- They also end immediately on logout, password change (other sessions), admin password reset, role change,
  deactivation or admin revocation.
- No signing secret exists to leak, and restarting the server does not sign anyone out.

**CSRF.** Two independent layers.
- A per-session synchronizer token must be echoed in `X-CSRF-Token` on every state-changing request. It's checked
  against the hash stored on that session, so a forged cookie or another session's token fails.
- An Origin check rejects cross-site state-changing requests, including login.

**Sign-in failures** return one message for wrong passwords, unknown accounts and inactive accounts. The audit log
records the real reason. Throttling counts failures per submitted email (whether the account exists or not) and per
IP, so a lockout can't be used to discover accounts.

**Roles** (enforced by the backend on every request; the frontend only uses them to shape navigation):

| Role | Purpose |
|---|---|
| `admin` | Everything, including user and session administration |
| `compliance_manager` | Rules (author and publish), oversight of every application, audit access, case work |
| `reviewer` | Case work on applications they own or are assigned to: intake, evidence, validation, resolution |
| `auditor` | Read-only across everything, including the audit trail; may export non-sensitive governance data |

**Ownership.** `app/core/authz.py` is the single resource-level policy: a user may act on a record they own or are
assigned to, or with the record type's override permission. Otherwise the API returns **404**, so it never confirms
that someone else's record exists. Today it protects sessions and user records. Applications, documents and reviews
will use the same policy.

**UI behaviour.**
- Protected routes redirect to sign-in.
- Navigation shows only the modules your role can use, and going to a forbidden route directly shows an access
  message. The API would refuse the data anyway.
- Two minutes before idle expiry, a banner offers **Stay signed in**.
- When the server ends a session, the next request returns you to sign-in with an explanation.
- **Account** lists your active sessions and can sign them out.

See [docs/API.md](docs/API.md) for the full matrix and the list of audited security events.

## Application Workspace

- **Applications.** Create, list (search, status/type filters, mine/all scope, sorting, pagination), view, edit,
  and move through `draft → processing → needs_review → completed`, plus `archive`/`restore`. Transitions require
  a reason and are audited.
- **Access.** The owner and members (contributor/viewer) get access to an application. Compliance managers,
  auditors and admins can see all applications; auditors are always read-only. Others get 404.
- **Upload.** Drag-and-drop or browse, two files at a time. The progress bar reflects bytes actually sent
  (XMLHttpRequest progress events), followed by an honest "Verifying on server…" step while the backend
  validates. Uploads can be cancelled. Validation rejections are final. Network, storage and server errors can be
  retried.
- **Validation.** See [docs/API.md](docs/API.md#upload-validation). The type comes from the file's content; the
  extension and declared MIME type must agree with it. PDF structure and page limits, image decode limits,
  duplicate detection (SHA-256) within an application, and cleanup on every failure path.
- **Storage.** Files live under `backend\var\storage` with random 48-hex-character names. The API never returns
  storage keys or paths.
- **Processing.** Background intake inspection re-verifies the hash and checks the text layer, embedded files,
  JavaScript and structural repairs. Statuses update live (polled while work is in flight). Failed or stalled
  jobs can be retried, and every attempt is kept.
- **Download and preview.** Files are fetched with your session and shown from a temporary `blob:` URL, so no
  durable link exists. Each download re-checks the SHA-256. PDFs and PNG/JPEG preview in-app. TIFF shows an
  explicit "preview isn't available" message, because browsers can't render TIFF.

## Extraction (Phase 4)

The extraction pipeline lives in `backend/app/extraction`. It is pure: no database access. Persistence, idempotency
and concurrency control live in `app/services/processing.py`.

1. **Text per page.** The PyMuPDF text layer is classified as `good`, `sparse`, `unusable` (garbled encoding) or
   `none`. Pages that are `none` or `unusable` are rendered at 300 DPI and sent to OCR. Every outcome is stored
   explicitly: `not_needed`, `completed`, `low_confidence`, `unavailable`, `failed` or `skipped_limit`. Raw page
   text is kept exactly as read, next to a whitespace-normalized copy.
2. **Fields.** Configurable definitions in `app/extraction/field_definitions.json` cover names, dates,
   identifiers, addresses and document numbers. Each type has its own normalizer and a strict Pydantic value
   schema. Raw values are never altered. OCR look-alike characters are flagged, not "fixed".
3. **Provenance.** Each field stores its raw value, normalized value, method, matched label, page, bounding box in
   displayed page space (rotation applied), a heuristic score, quality flags and alternative candidates.
4. **Corrections.** Corrections are append-only and keyed by document and field, so they survive reprocessing.
   Each one is validated by the field's normalizer, attributed to a person with a reason, and audited. The
   original extracted value is never modified.

**The extractor is a deterministic baseline.** It finds values only where a configured label is followed by `:`
or a dash on the same line. Addresses may continue onto lines directly below. It doesn't understand layouts,
tables, unlabeled values or handwriting, and it has only been validated on synthetic documents. The API and the
inspector state this on every view. Missing values are reported, never guessed. An AI-based extractor can plug
into the same pipeline later, but no AI provider is configured.

**OCR.** OCR needs Tesseract. It isn't installed on the development machine used to build this phase, so:
- scanned pages are recorded as `ocr_unavailable`, and the document goes to **needs review**;
- the OCR path is tested with a deterministic fake engine;
- a real end-to-end Tesseract test runs automatically wherever Tesseract is installed.

To enable it on Windows:
1. Install the UB Mannheim build of Tesseract.
2. Set `VERIFYFLOW_TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe` (or make sure `tesseract` is on
   `PATH`).
3. Restart the backend.
4. Use **Reprocess** on affected documents. The OCR engine is part of the idempotency key, so they really are
   re-extracted.

**Extraction Inspector.** Open it from a document's **Inspect** action. It shows:
- the server-rendered page, with stored coordinates highlighted, page navigation and per-page quality status;
- the raw or normalized page text;
- the field list, with status, raw-vs-normalized comparison, flags, alternatives and correction history;
- correction dialogs (validated server-side);
- Reprocess and Force re-extract actions, and Retry for failed processing.

## Evidence Intelligence Graph (Phase 5)

Open it from an application's **Evidence graph** action, or from the Evidence module. **Run analysis** compares
every configured field across the application's documents. It uses each document's current extraction, and
human corrections take precedence over extracted values.

- **No invented equivalences.** Only normalizations enabled per group are applied (case, diacritics, punctuation,
  separators, a date tolerance, configured address abbreviations), and each one is listed on the relationship.
  Nicknames, transliterations and abbreviations are never assumed.
- **Honest outcomes.** The outcomes are `pass`, `fail` (confirmed contradiction), `review` and `insufficient`.
  Near misses, reordered names, day/month swaps and OCR look-alike differences go to review. A low-quality value
  (for example, low-confidence OCR) can never produce a confirmed contradiction. Missing, invalid or unextracted
  values are insufficient evidence, never failures. Evidence quality and severity are reported separately from the
  outcome.
- **Traceability.** Every finding stores immutable references to the exact document, extraction run, field,
  correction, page and bounding box. The detail panel shows both values side by side, with a crop of each source
  page around the value and a deep link into the Extraction Inspector at that page and field. Explanations are
  generated from the stored structured evidence by templates; no AI is involved.
- **Priority.** A documented 0–100 score: severity 40, outcome 30, evidence quality 10, breadth 10, impact 10.
  Every factor's contribution is shown. It orders the review queue; it isn't a compliance decision.
- **Reproducibility.** Analyses are keyed by an input fingerprint (every value snapshot, comparator and engine
  version, config hash). An unchanged re-run reuses the stored analysis. Changes make it **stale**, and it stays
  visible exactly as stored until re-run. History is kept.
- **Graph.**
  - Columns are documents; select a document to collapse or expand it.
  - Rows are checks, and cells are the stored values.
  - Arcs are the stored comparisons, labelled match, differs, review or no data. Insufficient-evidence arcs are
    dashed.
  - Everything is keyboard-operable.
  - The **List** view shows the same findings ordered by priority, with comparison tables, for screen-reader and
    keyboard users.

## Compliance Studio (Phase 6)

Rules are **data, never code**. A rule is a JSON tree of `all` / `any` / `not` groups and leaf comparisons over a
typed field catalog: extracted fields, evidence outcomes and application attributes. Only allowlisted operators per
value type are accepted. Nothing users type is executed: there is no `eval`, no expression language, no
user-supplied regular expressions and no SQL. The full language is in [docs/API.md](docs/API.md#compliance-studio-declarative-rules-phase-6).

- **Honest outcomes.** `pass`, `fail`, `review`, `insufficient` and `not_applicable`. Missing data follows the
  rule's missing-data policy (default: insufficient), and low-confidence inputs (noisy OCR, stale evidence) follow
  its low-confidence policy (default: review). Missing data is never silently treated as a violation. Severity is
  configured separately from the outcome.
- **Not a legal determination.** A passing rule only means the configured condition held for the extracted
  evidence. Every screen and API response that shows rule outcomes says so.
- **Source, owner and approval.** Every rule has an owner (a user with `rules:manage`). Every version records its
  source reference (the policy, regulation or internal standard it implements), a change summary, its author,
  submitter, approver and review note. These appear on the rule page and in every validation result.
- **Lifecycle.** Draft → pending approval → published → retired (or rejected). Submitted versions are immutable
  and content-hashed. Submitting requires a source and change summary and all synthetic tests passing. Approval
  needs `rules:publish` and a **different person** from the author and submitter.
- **Effective dates.** `effective_from` is inclusive and `effective_to` exclusive. The newest published version
  whose start has passed is in force; superseded versions do not revive.
- **Tests.** Synthetic test cases (`"synthetic": true`, invented documents only) with expected outcomes run
  against stored versions or the editor's unsaved definition.
- **Comparison and simulation.** Compare any two versions as readable summaries plus a field-level diff. The
  what-if simulator evaluates a proposed version or unsaved edit against the rules in force for your visible
  applications and shows before/after outcomes. It is read-only: it creates or changes no rules, versions or
  runs, and only an audit entry is written.
- **Validation runs.** On an application page, **Run rules** evaluates every published version in force on the
  evaluation date. Each run stores the exact rule versions and a normalized input snapshot with fingerprints.
  Results show a trace down to document, page and field, with **Open source** links into the Extraction Inspector.
  **Check reproducibility** re-evaluates the stored snapshot and confirms the results are identical.

No rules are seeded. The register starts empty, and nothing is evaluated until someone authors a rule and a second
person approves it.

## Review and Resolution Center (Phase 7)

Every validation run opens a review item for each rule result that isn't a pass: **failure**, **uncertain** (low
confidence, or a rule that routes violations to people) and **missing evidence**. Items are ordered by a documented
priority (severity + category). Later runs update open items, resolve them when the rule passes, and keep an earlier
confirm/dismiss decision when the evidence is identical. The full model is in
[docs/API.md](docs/API.md#review-and-resolution-center-phase-7).

- **Split-pane review.** The left pane shows the original page with the value highlighted. The right pane shows the
  extracted field (original extraction, the value validation used, the current value and every correction), why the
  item needs review, the applicable rule with its source, owner and approver, related cross-document findings, and
  the full history including this rule's outcome across runs.
- **Decisions need reasons.** Escalating, confirming, dismissing (at least 10 characters), reopening, correcting and
  taking an item from someone else all require a reason, recorded with the reviewer and the time.
- **Who can do what.** Reading follows application access; acting needs `review:resolve` and edit access to the
  application. Escalated items and dismissing a critical failure need a compliance manager or administrator.
  Auditors are read-only. Reviewers can't author or publish rules.
- **Nothing is erased.** Original extractions, rule results and validation runs are immutable; review history is
  append-only (ORM guard and database triggers) and mirrored in the audit chain. Items are closed, never deleted.
- **Corrections revalidate.** A correction made from the review screen is appended (never overwriting the
  extraction). If a rule in force reads that field, the evidence analysis is refreshed and a new validation run is
  created, linked to the previous run, and the queue updates.
- **Conflicts and retries.** Every action carries the item version it was based on. If someone else acted first,
  the dialog keeps your text and offers to load the latest state. Each dialog sends a stable request id, so a retry
  after a network error isn't applied twice. Only comments are shown optimistically; decisions wait for the server.
- **Keyboard.** The queue supports ↑/↓/Home/End and Enter; dialogs trap focus, close on Escape and return focus.

## Design system, accessibility and motion (Phase 11)

Phase 11 is a UI/UX pass over all seven modules: Command Center, Applications, Evidence, Compliance, Review, Trust
and Governance. It changes how things look and behave, not what they do. Every control is either backed by a real
API call or disabled with a stated reason.

- **Tokens.** Colors, radii, shadows and durations are defined once in `src/index.css` (`@theme`). Deep navy is for
  structure, violet for primary actions and selection, cyan for secondary accents. Status colors (pass, fail,
  review, missing, info) are muted and always paired with a label or icon, so color is never the only cue. Text is
  Inter Variable with tabular numerals for figures.
- **Components.** Button (variants, sizes, loading state, `disabledReason`), Card/CardHeader, Field and inputs,
  Dialog, Tooltip, StatusPill, Notice, PageHeader, and loading, empty and error states in `src/components/ui/`.
  Pages use these instead of one-off styles.
- **Data tables.** Every data table uses the `data-table` class inside a `table-scroll` wrapper: one header style,
  row dividers, hover, right-aligned tabular `num` columns, `scope` on headers and a caption or `aria-label`. Wide
  tables scroll inside their card, never the page. `flush` removes the outer gutter inside padded panels and
  `dense` tightens rows in small summaries. Key/value layouts (for example a field's raw and normalized values)
  are not data tables and keep their own layout.
- **Layout.** A sidebar that turns into a drawer below `lg`, a topbar with the page title and account menu,
  breadcrumbs on every page (including each Governance tab) and `PageContainer` widths. Checked at 375 px (phone),
  768 px (tablet) and desktop on every route, with no horizontal page scroll. Rows that hold several actions, such as
  the document inventory, wrap onto a second line on small screens.
- **Keyboard and screen readers.** A skip link, a visible `:focus-visible` ring (kept in Windows forced-colors
  mode), focus trapping in dialogs and the mobile drawer with focus returned to the trigger (or to `<main>` if the
  trigger is gone), Escape to close, arrow-key menus, focusable graph nodes, and live regions for progress and
  results. A disabled button with a `disabledReason` stays focusable and announces why it is disabled. Small icon
  controls have a hit area of at least 24 px.
- **Charts.** Labelled bars, a legend when there are two series, a palette checked against color-vision
  deficiencies, and a table view under each chart. The evidence graph has a list view with the same content.
- **Motion.** Motion for React handles route transitions, dialog entry and exit, the evidence detail panel, graph
  expand/collapse and node/edge changes, selection highlighting, and notices for review and save outcomes. Hover,
  press and focus feedback is plain CSS. Durations are 120–260 ms and staggers are capped at 150 ms (`src/lib/motion.ts`).
  Upload and processing progress come from real XHR progress events and job status. Nothing simulates processing.
- **Showcase layer (redesign).** Every module opens with a dark hero banner and its own animated illustration
  (`src/components/art/`): radar, folders, network, scales, checklist, shield, charts. The sidebar has glowing icon
  tiles, cards lift with a light sweep on hover, and routes fade in with a short blur. The illustrations are
  decorative (`aria-hidden`), and their ambient movement (floating, pulsing, flowing links) is CSS only.
- **Evidence Intelligence Graph.** A hero with an animated consistency ring, outcome tiles that filter the checks,
  a rail of first-page thumbnails for every document, and four views: **Overview** (each check with documents
  grouped by the value they hold, so a contradiction is a second group), **Network** (one check at a time,
  documents on a ring, stored comparisons as links; hover a document to trace its links), **Matrix** (every check
  against every document) and **List**. Evidence opens in a side drawer with the same focus trap as dialogs.
- **Reduced motion.** `MotionConfig reducedMotion="user"` drops transforms and layout animation but keeps opacity
  changes, so state changes stay visible. CSS transitions, the decorative ambient animations, shimmer and spinners
  stop under `prefers-reduced-motion`, and text labels still say what is happening.

Tests for the shared behaviors (explained disabled buttons, tooltips, the dialog and drawer focus traps, the
account menu and breadcrumbs) are in `src/test/design.test.tsx`.

## Command Center and Governance & Insights (Phase 10)

Every number comes from a database aggregate over stored records. Each metric has a definition, a time basis and a
data source, shown behind the ⓘ next to it and listed in [docs/API.md](docs/API.md#governance-and-insights-phase-10).
Nothing is estimated, and an empty system shows zeros and empty states, not sample charts.

- **Scope.** Metrics cover only the applications you can see, optionally narrowed by application type, and can
  exclude synthetic demo applications (a notice says how many are included).
- **Now vs. in the window.** "Now" metrics describe current records and ignore the date window. "In window" metrics
  count events inside the selected UTC days (7/30/90/365 days or custom).
- **No double counting.** Findings use each application's latest validation run; historical case counts use the
  latest run per application inside the window; run counts are labelled as runs.
- **Engine vs. people.** Rule failures, review-required and insufficient-evidence results from the engine are separate
  tiles from failures a person confirmed and findings a person dismissed. False-positive rates come only from
  reviewer decisions.
- **Command Center.** Current-state tiles that open the filtered review queue or application list, findings by
  outcome, and validation runs over the last 30 days.
- **Governance & Insights tabs.** Insights (applications, findings by outcome × severity, cross-document findings,
  validation runs, backlog, documents and processing, extraction quality); Review & false positives (backlog by age,
  workload, false positives by rule and category); Rules & validation (rule-version usage, paginated validation
  history, rule governance history with the four-eyes check); Audit history (filters by action group, outcome, dates
  and text); Exports; Users & roles.
- **Exports.** CSV or JSON for metrics, review items, validation results, rule history and audit events
  (`exports:create`: admins, compliance managers, auditors). Extracted document values need `exports:sensitive`
  (admins, compliance managers), an explicit opt-in and a reason. Page text is never exported. Every export, and every
  refused one, is recorded in the audit trail with the file's SHA-256.
- **Charts.** Labelled bars (each row carries its own label and icon, so color is never the only cue), daily bar
  charts with a legend for two series, a hover tooltip and a table view, using a palette validated for color-vision
  deficiencies.

## AI assistance (Phase 9)

AI is **advisory and optional**. With the defaults (`VERIFYFLOW_AI_PROVIDER=disabled`) nothing leaves the server and
every screen shows deterministic explanations instead. Nothing AI returns is read by the rule engine, trust checks or
review decisions, and the deterministic result is always shown next to it as the authoritative one. The full model is
in [docs/API.md](docs/API.md#ai-assistance-phase-9).

- **What it does.** Explains a rule result (on the review screen) or a cross-document finding (in the evidence graph)
  in plain language; suggests a document type from a fixed list and field values quoted from the page (in the
  Extraction Inspector). Suggestions are never applied: a reviewer corrects a field through the audited correction
  workflow.
- **Grounded explanations.** Every statement must cite stored records (rule result, rule version, extracted field,
  correction, finding, compared value). Each citation is checked against the database and against what was sent;
  statements with an unverifiable citation are removed, and so are statements that claim authenticity, an approval or
  rejection, or that a deterministic result is wrong. Each citation links to the evidence.
- **Data egress.** `VERIFYFLOW_AI_DOCUMENT_EGRESS` decides what may leave: `none` (default: rule and finding metadata
  only), `extracted_values`, or `page_text` (needed for classification and field suggestions). Identifier values are
  masked by default, and each interaction stores a manifest of what was sent.
- **Prompt injection.** Document text is framed as data and its delimiters neutralized; the model has no tools and
  must answer in a fixed schema; the API key never appears in a request. Text that looks like instructions to an AI is
  flagged to the reviewer.
- **Cost and reliability.** Input cap, per-process and per-user rate limits, and a daily budget are checked before a
  call; each attempt has a timeout and only transient failures are retried, a bounded number of times. Identical
  requests reuse the stored answer. Invalid JSON, schema mismatches, empty or truncated output and refusals are
  discarded and reported. Provider health (last success, last error, consecutive failures) and today's spend are on the
  Command Center, where an administrator can run a connection check.
- **Records.** Every provider call is stored append-only in `ai_interactions` and mirrored in the audit chain as
  `ai.requested` (`ai.blocked` when refused before sending). Prompts are not stored; logs carry metadata only.

### Enabling Claude

```powershell
# backend\.env, or better the server environment / a secret manager
VERIFYFLOW_AI_PROVIDER=anthropic
VERIFYFLOW_AI_API_KEY=<your Anthropic API key>
# Optional: let explanations include values, or allow page text for classification and field suggestions
VERIFYFLOW_AI_DOCUMENT_EGRESS=extracted_values
```

The default model is `claude-opus-5-5` (`VERIFYFLOW_AI_MODEL`), with server-side refusal fallback on
(`VERIFYFLOW_AI_REFUSAL_FALLBACK`). Set `VERIFYFLOW_AI_INPUT_USD_PER_MTOK` / `VERIFYFLOW_AI_OUTPUT_USD_PER_MTOK` if you
change the model, so the budget estimate stays right. Restart the backend after changing AI settings. Before enabling
`extracted_values` or `page_text`, check that sending that data to the provider is allowed for your documents.

### Enabling Groq

```powershell
# backend\.env
VERIFYFLOW_AI_PROVIDER=groq
VERIFYFLOW_AI_API_KEY=<your Groq API key, starts with gsk_>
VERIFYFLOW_AI_MODEL=openai/gpt-oss-120b
VERIFYFLOW_AI_INPUT_USD_PER_MTOK=0.15
VERIFYFLOW_AI_OUTPUT_USD_PER_MTOK=0.75
```

The Groq adapter (`app/integrations/ai/groq_provider.py`) calls Groq's OpenAI-compatible API with `httpx` and asks for
JSON matching the task schema. Everything else is unchanged: the egress policy, identifier masking, citation checks,
content guard, rate limits and daily budget all run in the shared gateway. Check the prices on Groq's pricing page for
the model you choose. Groq keys (`gsk_…`) are redacted from logs.

## Security and data handling

| Area | Implementation |
|---|---|
| Secrets | Nothing is hardcoded. No signing secret is needed. Local `.env` files, databases, `backend\var\` (uploads), virtual environments and build output are git-ignored. |
| Passwords | Argon2id (argon2-cffi defaults; hashes are transparently upgraded on sign-in if parameters change). Minimum 12 characters, three character classes. |
| Audit trail | Events are SHA-256 hash-chained. Updates and deletes are blocked by ORM guards and database triggers. `GET /api/v1/audit/verify` re-hashes the whole chain. |
| Storage | Private directory, random keys, file type checked from the content itself, size limit, SHA-256 hashing, protection against path traversal. Upload endpoints arrive with the Application Workspace phase. |
| AI | Off by default. The API key is backend-only (`SecretStr`, never returned, logged or stored). What may leave is set by the egress policy; outputs are schema-validated, citations verified against the database, and nothing AI returns changes a deterministic result. |
| Data | The repository contains no customer data and no seeded demo records. |

## Known limitations

- AI rate limits and provider health are kept in process memory: they reset on restart and aren't shared between
  workers. The daily budget is stored in the database and is shared. Put a gateway rate limit in front for
  multi-worker deployments.
- AI explanations are generated on request, not automatically. A stored explanation is marked stale when its records
  change (for example after a new validation run); regenerate it to update.
- Field suggestions and document-type suggestions are display-only. Applying one is a manual correction in the
  Extraction Inspector; the document type declared at upload isn't changed from the AI panel.
- AI tasks see the text-layer/OCR text of the current extraction only, not page images, so layout-only or handwritten
  content is invisible to them.
- The content guard that drops authenticity, decision and override claims is pattern-based. It is a second line of
  defence behind the prompt, the schema and citation verification, and can miss unusual phrasings or drop a harmless
  sentence.
- The Anthropic adapter is tested against a mocked SDK client; no test calls the real API.
- Review items come from rule results only. Evidence findings are shown as comparison evidence inside an item but
  don't open items of their own.
- Corrections made in the Extraction Inspector don't trigger revalidation; corrections made from a review item do.
  The review screen flags a value that changed since validation.
- "Request document" records the request and pauses the item; there's no notification or upload link to the
  applicant. Resume the item after uploading the document.
- No notifications (email or in-app) for assignment or escalation yet.
- Migrations run with SQLite foreign-key enforcement off and verify integrity afterwards. Before this was fixed,
  upgrading a database to 0008 deleted the `rule_results` of existing validation runs (an `ON DELETE CASCADE`
  fired by SQLite's table rebuild). Databases upgraded with the fixed version are unaffected; a regression test covers it.
- Rules can reference only the configured catalog fields (one value per document) and current evidence outcomes.
  There are no cross-field arithmetic, aggregate counts per field, or custom functions — by design, since every
  operator must be allowlisted and testable.
- Validation runs are on demand. They don't re-run automatically when documents, corrections or rules change.
- Simulation evaluates at most 50 applications per request (the most recently updated visible ones, unless
  specific application ids are given).
- Four-eyes approval needs at least two users with `rules:publish`. A single-administrator installation can author
  but not publish rules.
- Insights are computed on request from the database (no cache or pre-aggregation). This is exact, but on very large
  installations the overview's queries will need indexes tuned or a reporting replica.
- Day buckets and windows are UTC days. There is no per-user time zone yet.
- False-positive rates depend on reviewers recording confirm/dismiss decisions; items left open or closed
  automatically by a later run don't count.
- Rule governance history is derived from the rule-version records (created, submitted, approved/rejected, retired).
  Edits to a draft before submission aren't individually listed; the audit trail has them.
- Exports are built in memory and capped at 50,000 rows per file.
- The Governance & Insights module is visible to admins, compliance managers and auditors. Reviewers see their own
  scoped metrics on the Command Center.
- OCR requires a local Tesseract install.
- Sign-in throttling is per email and per IP. A distributed attack from many IPs against many accounts is only
  slowed by the per-email limit; put a WAF or reverse-proxy rate limit in front for production.
- Client IPs come from the direct connection. Behind a reverse proxy, configure it to pass the real client address
  (for example uvicorn `--proxy-headers` with `--forwarded-allow-ips` limited to the proxy), or per-IP throttling and
  audit IPs will all show the proxy.
- There's no multi-factor authentication or SSO yet, and no self-service password reset. Administrators reset
  passwords, which is audited.
- In the default `inline` processing mode (local development), jobs run inside the API process, and a restart can
  strand one until it's retried. Production should use `VERIFYFLOW_PROCESSING_MODE=worker` with the `worker`
  process, which recovers interrupted jobs automatically.
- Document storage is a local filesystem path (a persistent volume). Object storage such as S3 isn't supported yet.
- No automated deletion or retention purge for documents and their records exists. Only ended sessions can be
  pruned (`prune-sessions`).
- The baseline extractor only handles "Label: value" layouts. Real-world documents need a stronger extractor.
- OCR text orientation detection (OSD) isn't enabled. Scanned pages whose text is rotated inside the image may OCR
  poorly.
- A multi-line field's highlight is one union rectangle. For addresses it can also cover the label area.
- Corrections can only be made against the current run's fields. Older runs are view-only.
- Viewing page images isn't audited, to avoid flooding the audit trail. Downloads are audited.
- Evidence analysis runs synchronously when requested. It isn't re-run automatically after uploads or
  corrections; the page shows **stale** instead.
- Comparison is pairwise within each group (capped at 25 values; beyond that, each value is compared with the
  first). Cross-group reasoning (for example, a name versus an account holder in a differently named field)
  requires configuring both field keys in one group.
- The graph lays documents out as columns. Applications with many documents need horizontal scrolling;
  collapsing columns helps, and the List view always works.
- Documents can't be deleted (by design for an evidence system); applications are archived, not deleted.
  Retention rules aren't implemented.
- Upload limits are enforced per request. There is no per-user storage quota yet.
- `.claude/launch.json` (dev-server definitions for Claude Code's browser preview) uses absolute paths for this machine.

## API

See [docs/API.md](docs/API.md) and the live OpenAPI UI at <http://127.0.0.1:8000/api/docs> (development; off in production unless `VERIFYFLOW_EXPOSE_API_DOCS=true`).
