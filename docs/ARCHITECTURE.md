# VerifyFlow AI — architecture

VerifyFlow is a modular monolith: one FastAPI process and one React single-page app, with module boundaries kept in
code rather than in separate services. Every compliance outcome is computed deterministically from stored records.
AI is optional and advisory, and never feeds a decision.

```
Browser (React SPA, same origin via the Vite proxy or a reverse proxy)
  │  HttpOnly session cookie + X-CSRF-Token header
  ▼
FastAPI  app/main.py
  ├─ middleware    request ID, access log, Origin check, error envelope
  ├─ api/routes    thin HTTP layer: parse/validate (Pydantic), resolve user + permission, call a service
  ├─ services      business operations and transactions; every state change writes an audit event
  ├─ engines       pure, deterministic logic with no I/O:
  │                  extraction/  evidence/  rules/  trust/  insights/definitions
  ├─ integrations  ai/ (provider protocol, Disabled + Anthropic adapters, guarded gateway)
  ├─ worker        app.cli worker: runs queued processing jobs from the database (production)
  ├─ models        SQLAlchemy ORM; immutability guards on append-only tables
  └─ storage       private local storage outside the web root (generated keys, SHA-256)
  ▼
SQLite (development) / PostgreSQL (production), schema owned by Alembic migrations 0001–0011
```

## Layers and rules

| Layer | Location | Responsibility | Must not |
| --- | --- | --- | --- |
| Routes | `app/api/routes/` | HTTP shape, permission dependency, status codes | contain business rules or raw SQL beyond simple reads |
| Schemas | `app/schemas/` | Request/response contracts (mirrored in `frontend/src/lib/types.ts`) | accept unvalidated input |
| Services | `app/services/` | Transactions, ownership checks (`core/authz.py`), audit writes | call an AI provider for a decision |
| Engines | `app/extraction`, `app/evidence`, `app/rules`, `app/trust` | Deterministic computation over snapshots | perform network or database I/O (except trust connectors, behind an interface) |
| Integrations | `app/integrations/ai/` | Provider adapters behind `AIProvider` | hold the only copy of a result |
| Models | `app/models/` | Tables, constraints, immutability hooks | be changed without a migration |

## Modules

| Module (UI) | Backend | Frontend feature |
| --- | --- | --- |
| Command Center | `insights_service` (current-state metrics) | `features/command-center` |
| Application Workspace | `application_service`, `document_service`, `processing`, `extraction_service` | `features/applications`, `features/extraction` |
| Evidence Intelligence Graph | `evidence/` engine, `evidence_service` | `features/evidence` |
| Compliance Studio | `rules/` engine, `rule_service`, `validation_service` | `features/compliance` |
| Review and Resolution Center | `review_service` | `features/review` |
| Trust and Authentication Center | `trust/` checks and connectors, `trust_service` | `features/trust` |
| Governance and Insights | `insights_service`, `export_service`, audit routes, users | `features/governance`, `features/insights` |

AI assistance (`ai_service`, `assist/`) sits beside these modules and is surfaced in the review, evidence,
extraction and compliance screens.

## Request lifecycle (state-changing call)

1. Middleware assigns a request ID and checks `Origin` against the allowed origins. Uploads refuse a missing or
   oversized `Content-Length` before reading the body, and stream with a hard byte limit.
2. The session dependency resolves the cookie to a server-side session (only its SHA-256 is stored), slides the idle
   window, and checks the CSRF token against that session.
3. The permission dependency checks the role (`core/roles.py`). The service then checks ownership/membership
   (`core/authz.py`) and answers 404, not 403, for records the user can't see.
4. The service does the work in one transaction and appends an audit event to the hash chain. The chain head row is
   locked, so concurrent appends serialize.
5. Errors leave as `{"error": {"code", "message", "details"}}`. Unhandled exceptions are logged with redaction and
   returned as `internal_error`.

## Data flow of one application

```
upload ─► intake inspection ─► extraction run ─► evidence analysis ─► validation run ─► review items
  │        (type by content,     (pages, fields,    (pairwise field     (rule versions in    (failures, uncertain,
  │         limits, SHA-256)      raw + normalized,  comparisons,        force + input        missing evidence)
  │                               page boxes)        findings, priority) snapshot, traces)        │
  │                                                                                               ▼
  └────────────── trust verification (hash re-check, signatures, anchors, revocation, registries)  correction ─► revalidation
                                                                                                   (new run linked to the old)
```

Every arrow writes new rows; nothing earlier is overwritten. Corrections are appended next to the original
extraction. A revalidation creates a new run whose `previous_run_id` points at the run it supersedes.

## Immutability and reproducibility

- **Append-only tables:** audit events (ORM guard plus a database trigger, hash-chained), review actions,
  field corrections, evidence findings, trust verifications and AI interactions.
- **Immutable once submitted:** rule versions. Changes create a new draft version; publication needs four-eyes
  approval.
- **Reproducible:** each validation run stores the exact rule-version definitions and the normalized input snapshot.
  `GET …/validation-runs/{id}/reproduction` re-evaluates them and reports differences.

## Determinism boundary

Rule evaluation, evidence comparison, priority scoring and trust checks are pure functions of stored data. The AI
gateway (`integrations/ai/gateway.py`) is the only path to a model. It enforces input caps, rate and budget limits,
timeouts, bounded retries and strict output schemas. Its output is only *displayed*: citations are verified against
the database, authenticity, decision and override claims are filtered out, and nothing it returns is read by an engine.

## Frontend

- `src/lib/api.ts`: the typed client (CSRF header, upload progress via XHR, error envelope → `ApiError`).
  `src/lib/types.ts`: the contracts.
- TanStack Query holds server state, React Hook Form + Zod handle forms (the server re-validates everything), and
  React Router drives lazy-loaded module routes.
- `src/components/ui` and `src/components/layout` hold the design system and shell (see the README's Phase 11
  section).

## Deployment notes

- Run behind a TLS-terminating reverse proxy that serves the SPA and `/api` from one origin. Pass the real client IP
  (`--proxy-headers`, `--forwarded-allow-ips`).
- Use PostgreSQL in production (SQLite is refused), through the `psycopg` driver. The whole test suite also runs on
  PostgreSQL (`VERIFYFLOW_TEST_POSTGRES_URL`).
- Run processing in worker mode (`VERIFYFLOW_PROCESSING_MODE=worker`). The API only queues jobs, and one or more
  `python -m app.cli worker` processes run them from the database and recover interrupted ones
  (`app/services/worker.py`).
- `GET /api/v1/health/ready` checks the database, migration level and storage, and reports the processing backlog.
  See [DEPLOYMENT.md](DEPLOYMENT.md).
