# VerifyFlow AI — deployment guide (Phase 13)

This guide prepares a production deployment. **Nothing has been deployed**, no hosting resources were created, and
no real credentials appear anywhere in this repository. Every step that needs your infrastructure or secrets is
marked **[you provide]**.

> **Readiness statement.** The application, migrations, backup/restore and smoke tests were exercised locally against
> PostgreSQL 16 in production mode (results below). The container images, the nginx configuration, TLS, a real host,
> off-site backups and monitoring **were not tested** (no container runtime or host was available). Treat the first
> staging deployment as the test of those parts. It is **not production-ready** until the pre-release checklist
> passes on staging.

## What was verified locally

| Check | How | Result |
| --- | --- | --- |
| Backend tests on SQLite | `pytest` | all pass, 1 skipped (Tesseract not installed) |
| Backend tests on PostgreSQL 16.2 | `VERIFYFLOW_TEST_POSTGRES_URL=… pytest` (each test on its own database copied from a migrated template) | all pass, 1 skipped |
| Migrations on PostgreSQL | `alembic upgrade head`, `alembic check`, `downgrade base`, `upgrade head` | pass after fixing `0011` (boolean default `0` was invalid on PostgreSQL) |
| Append-only audit trigger on PostgreSQL | raw `UPDATE audit_events` on a restored database | refused: `audit_events is append-only` |
| Backup and restore drill | `deploy/backup.sh` → `deploy/restore.sh` into a new database and empty storage | identical row counts; `verify-audit` valid (19 events); `verify-storage` 5/5 documents match |
| Restore safety | restore without `CONFIRM_RESTORE=yes`; corrupted archive; altered stored file | refused (exit 2); refused on checksum (exit 1); `verify-storage` reports the altered document (exit 1) |
| Production-mode rehearsal | API with `VERIFYFLOW_ENVIRONMENT=production` and a separate worker process on PostgreSQL | `deploy/smoke.sh`: 18/18 checks pass (HTTPS header checks skipped: plain HTTP) |
| Durable worker | upload through the production API | API answers `queued`; the worker process finishes it in 3 s |
| Production config guard | local `.env` enabled the synthetic registry | API refused to start in production mode, as designed |
| Dependency audit | `pip-audit -r requirements.txt`; `npm audit --omit=dev` | `No known vulnerabilities found`; `found 0 vulnerabilities` (after the upgrades below) |
| Frontend | `vitest`, `tsc -b`, `eslint`, `npm run build` | see the final results in the Phase 13 summary at the end |

Not verified: building or running the Docker images, nginx (TLS, headers, rate limits, SPA routing), certificate
issuance, a managed database, off-site backup copies, log shipping and alerting, OCR with Tesseract, and load.

## Architecture in production

```
Internet ──HTTPS──► web (nginx: TLS, security headers, per-IP rate limits, SPA, /api proxy)
                       │
                       ▼
                    api (uvicorn, 2 workers) ──┐
                    worker (app.cli worker) ───┼──► PostgreSQL (managed, or the bundled container)
                    migrate (one-shot) ────────┘
                    api + worker share the private storage volume (never served by nginx)
```

Files in `deploy/`:

| File | Purpose |
| --- | --- |
| `.env.production.example` | Every production setting with safe values and `REPLACE_ME` placeholders for secrets |
| `docker-compose.yml` | db, migrate, api, worker, web; read-only containers, non-root API user, private volumes |
| `nginx/verifyflow.conf.template` | HTTPS, HSTS, CSP, request limits, upload size, SPA fallback, `/api` proxy, docs blocked |
| `backup.sh` / `restore.sh` | Database + storage backup with manifest and retention; checksum-verified restore |
| `smoke.sh` | Pre- and post-release smoke checks |

Images: `backend/Dockerfile` (API and worker; Python 3.11, Tesseract, non-root) and `frontend/Dockerfile` (Node build,
then nginx).

## Choosing a host

Any Linux host that runs containers fits. Two suitable shapes:

1. **One VM with Docker Compose** (simplest): 2 vCPU / 4 GB RAM to start, an encrypted data disk for the `storage`
   volume, and preferably a **managed PostgreSQL** with automated backups and point-in-time recovery. Use the
   compose file as is, or remove the `db` service when using the managed database.
2. **A container platform** (ECS, Cloud Run, Azure Container Apps, Kubernetes): run `api` and `worker` from the
   same image, run `alembic upgrade head` as a release job, put the SPA behind the platform's load balancer or a CDN,
   and use persistent file storage (EFS, Azure Files, a persistent volume) for `VERIFYFLOW_STORAGE_DIR`. Object
   storage (S3 and similar) is **not supported yet**; storage is a local filesystem path.

Both shapes create paid resources. Choose and create them yourself **[you provide]**.

## Steps that need your credentials or infrastructure

| Step | What you provide |
| --- | --- |
| Host or platform account, DNS record for the domain | Hosting account, domain and DNS access |
| TLS certificate | certbot/Let's Encrypt on the host, or your load balancer's certificate |
| PostgreSQL | A managed instance (recommended) or the bundled container; a strong password; `sslmode=require` for remote databases |
| Secrets | `POSTGRES_PASSWORD`, `VERIFYFLOW_DATABASE_URL`, optionally `VERIFYFLOW_AI_API_KEY`, injected from a secret manager |
| First administrator | `python -m app.cli create-user … --role admin`, run by you, password typed at the prompt |
| Second approver | A second user with `rules:publish` (compliance manager), required for four-eyes rule approval |
| Smoke account | An `auditor` user for `smoke.sh`, with its password in your secret store |
| Off-site backup target | An encrypted bucket or backup service, and the key to encrypt copies |
| Monitoring and alerting | An uptime monitor, a log destination, and someone to receive alerts |
| Trust anchors (optional) | The CA certificates you actually trust, if you verify PDF signatures |
| AI (optional) | A provider key, and a decision on `VERIFYFLOW_AI_DOCUMENT_EGRESS` (default `none`) |

## Configuration and secrets

1. Copy `deploy/.env.production.example` to `deploy/.env.production` on the server, `chmod 600` it, and replace every
   `REPLACE_ME`. It's git-ignored. Better still, inject the `[secret]` values from your platform's secret manager.
2. The API **refuses to start** in production if SQLite is configured, a CORS origin is `http://`, cookies aren't
   `Secure`, the synthetic registry connector is enabled, or a connector or AI URL isn't `https://`.
3. **HTTPS and cookies:** cookies are `__Host-`, `Secure`, `HttpOnly`, `SameSite=Lax`. The SPA and `/api` share one
   origin, so `VERIFYFLOW_CORS_ORIGINS` lists only that origin.
4. **API docs** (`/api/docs`) are off in production (`VERIFYFLOW_EXPOSE_API_DOCS`) and blocked again by nginx.
5. **Client IPs:** the API trusts `X-Forwarded-For` only from `172.16.0.0/12`, the Docker network range. On another
   platform, set uvicorn's `--forwarded-allow-ips` to your proxy's address, or sign-in throttling and audit IPs will
   be wrong.

## Rate limits and upload restrictions

| Layer | Limit |
| --- | --- |
| nginx, per IP | API 20 req/s (burst 40); sign-in 10/min (burst 5); uploads 30/min (burst 10); body ≤ 27 MiB |
| API sign-in | 5 failures per email and 30 per IP in 15 minutes (configurable) |
| API uploads | Content-Length required; ≤ 25 MiB; type detected from content; ≤ 500 PDF pages; ≤ 60 MP images; ≤ 200 documents per application; JavaScript/encryption/embedded files flagged |
| AI (if enabled) | per-process and per-user rate limits, daily budget |

## Database migrations

- The `migrate` service runs `alembic upgrade head` before `api` and `worker` start. If it fails, they don't start.
- Every migration has a downgrade and was round-tripped on PostgreSQL. Downgrades can drop data that newer versions
  added, though, so **restore from the pre-release backup** rather than downgrading in production (see Rollback).
- `GET /api/v1/health/ready` reports `migrations: behind` (HTTP 503) if the database is older than the code.
- Before each release: `alembic check` (models match migrations); on staging, upgrade a copy of production data.

## Background processing

Set `VERIFYFLOW_PROCESSING_MODE=worker` (the template does). The API only records a queued job; the `worker` service
runs jobs from the database:

- Jobs survive API and worker restarts (they are rows, not in-memory tasks).
- Several workers can run (`docker compose up -d --scale worker=2`). Each job is claimed by a conditional `UPDATE`.
- A job still `running` after `VERIFYFLOW_PROCESSING_STALE_MINUTES` is marked `interrupted` and re-queued, up to
  `VERIFYFLOW_PROCESSING_MAX_ATTEMPTS`. After that it stays failed for a person to retry. Each recovery is audited
  (`document.processing_recovered`).
- OCR runs in the worker container, keeping CPU load away from the API.

## Logging, monitoring and health checks

| Endpoint | Use | Healthy |
| --- | --- | --- |
| `GET /api/v1/health` | liveness (container health check) | 200, `status: ok` |
| `GET /api/v1/health/ready` | readiness (load balancer, uptime monitor) | 200; database, migrations and storage `ok` |

`/health/ready` also returns `processing.queued`, `oldest_queued_seconds` and `stale_running`. Alert when **[you
provide]**:

- `/health/ready` isn't 200 for 2 minutes.
- `oldest_queued_seconds` > 600 (the worker is down or overloaded).
- `stale_running` > 0.
- Error-level log lines or HTTP 5xx rates rise.
- Disk space on the storage volume falls below 20 %.
- The nightly backup didn't produce a new complete directory.
- `python -m app.cli verify-audit` (run daily from cron) exits non-zero.

Logs: `VERIFYFLOW_LOG_FORMAT=json` writes one JSON object per line to stdout. Collect it with your platform's log
driver. Every line carries the request ID, which also appears on audit events. Passwords, tokens, cookies, API keys
and document text are redacted or never logged.

## Backups, restoration and retention

**What to back up:** the PostgreSQL database **and** the storage volume, together. Neither is useful without the
other. `deploy/backup.sh` dumps the database first and then archives storage, which guarantees every file a backed-up
row refers to is in the archive. It writes a `MANIFEST` with SHA-256 checksums and prunes backups older than
`RETENTION_DAYS`.

```bash
# Nightly from cron on the host (example). The database runs in the compose stack here.
DATABASE_URL="postgresql://verifyflow:${POSTGRES_PASSWORD}@localhost/verifyflow" \
PG_DUMP="docker compose -f /srv/verifyflow/deploy/docker-compose.yml exec -T db pg_dump" \
STORAGE_DIR=/var/lib/docker/volumes/verifyflow_storage/_data \
BACKUP_DIR=/srv/backups/verifyflow RETENTION_DAYS=35 \
/srv/verifyflow/deploy/backup.sh
```

Then copy the new backup **off the host, encrypted** **[you provide]**. Backups contain personal data from documents:
treat them like the production database. With a managed database, also keep the provider's point-in-time recovery
on. It covers the database, but not the storage volume.

**Restore** (for a disaster or a rollback):

```bash
docker compose -f deploy/docker-compose.yml stop api worker
CONFIRM_RESTORE=yes DATABASE_URL=… STORAGE_DIR=… PG_RESTORE="…exec -T db pg_restore" \
  deploy/restore.sh /srv/backups/verifyflow/verifyflow-<timestamp>
docker compose -f deploy/docker-compose.yml run --rm api python -m app.cli verify-audit
docker compose -f deploy/docker-compose.yml run --rm api python -m app.cli verify-storage
docker compose -f deploy/docker-compose.yml up -d
```

The restore checks every checksum first, refuses to run without `CONFIRM_RESTORE=yes`, and moves any existing storage
aside rather than deleting it. **Drill a restore on staging at least once a quarter.**

**Retention policy:**

| Data | Retention | Mechanism |
| --- | --- | --- |
| Audit events | Permanent (append-only, hash-chained) | Database trigger; never pruned |
| Documents, extractions, evidence, validation runs, review history, trust verifications | Kept for the life of the application (an evidence system); applications are archived, not deleted | **No automated deletion is implemented.** Decide a legal retention period with your compliance owner; deleting records would need a reviewed, audited purge feature that doesn't exist yet |
| Ended sessions | 90 days (suggested) | `python -m app.cli prune-sessions --older-than-days 90`, weekly from cron; audited |
| Login attempts | 1 day | Pruned automatically at sign-in |
| Backups | 35 days locally (`RETENTION_DAYS`), longer off-site per your policy | `backup.sh` pruning; off-site lifecycle rules **[you provide]** |
| AI interactions (if enabled) | Permanent (append-only) | Never pruned |

## Dependency and vulnerability checks

Run before every release (both need network access to the advisory databases):

```bash
pip install pip-audit && pip-audit -r backend/requirements.txt
cd frontend && npm audit --omit=dev
```

Phase 13 found and fixed: Pillow 11.0.0 (49 advisories) → 13.0.0, python-multipart 0.0.20 (6) → 0.0.31, Starlette
0.41.3 (7, via FastAPI 0.115.6) → Starlette 1.9.0 via FastAPI 0.161.1, and react-router-dom 7.1.1 (13 advisories,
including client-side open redirect and XSS) → 7.18.4. The full backend suite passes on the new versions.

Remaining: 16 advisories in **development-only** frontend tools (vitest, eslint, vite/esbuild dev server, tinypool).
They're not in the production bundle, but they do affect developer machines. Upgrading means major versions of vitest
and vite, which should be a separate change.

## Release procedure

1. Pre-release checklist (below) passes on staging with the release candidate.
2. Take a backup (`backup.sh`) and confirm the new directory has a `MANIFEST`. Note its name for rollback.
3. Build and tag images with the release version:
   `VERIFYFLOW_VERSION=1.2.3 docker compose -f deploy/docker-compose.yml --env-file deploy/.env.production build`
4. Deploy: `VERIFYFLOW_VERSION=1.2.3 docker compose -f deploy/docker-compose.yml --env-file deploy/.env.production up -d`
   (the `migrate` service runs first).
5. Post-release checklist (below).

## Rollback procedure

Decide within the post-release window. Keep the previous version's image tag and the pre-release backup.

1. **Code only, no migration in the release:** redeploy the previous tag.
   `VERIFYFLOW_VERSION=<previous> docker compose … up -d api worker web`, then run `smoke.sh`.
2. **The release included a migration:** stop writes (`docker compose stop api worker`), restore the pre-release backup
   with `restore.sh` (database **and** storage), deploy the previous tag, run `verify-audit`, `verify-storage` and
   `smoke.sh`, then reopen. Anything users did after the release is lost. Announce the rollback window.
3. **Never** edit or delete audit rows to "undo" a release. The chain would no longer verify.
4. Record the rollback (what, why, which backup) in your change log.

## Pre-release smoke checklist (staging)

- [ ] `pytest` passes on SQLite **and** with `VERIFYFLOW_TEST_POSTGRES_URL` pointing at a disposable PostgreSQL
- [ ] `ruff check .`, `alembic check`, `npm run typecheck`, `npm run lint`, `npm test`, `npm run build` all pass
- [ ] `pip-audit` and `npm audit --omit=dev` report no unresolved production advisories
- [ ] Images build; containers start; `migrate` exits 0
- [ ] `BASE_URL=https://staging… SMOKE_EMAIL=… SMOKE_PASSWORD=… deploy/smoke.sh` exits 0, including the HTTPS checks
- [ ] Upload a synthetic document: it goes `queued` → `ready`, and OCR works on a scanned synthetic PDF
- [ ] Run the end-to-end flow once in the browser: create → upload two documents → evidence → validation → review →
      correction → revalidation → trust check → audit log → dashboard
- [ ] Open the app on a phone and a tablet; no horizontal page scrolling; reduced-motion setting respected
- [ ] Browser console shows no CSP violations on any page (document preview and page images load)
- [ ] Restore the latest staging backup into a scratch database; `verify-audit` and `verify-storage` pass
- [ ] `/api/docs` returns 404; HTTP redirects to HTTPS

## Post-release smoke checklist (production)

- [ ] `deploy/smoke.sh` against production exits 0
- [ ] `/api/v1/health/ready` is 200, with `migrations: ok` and `stale_running: 0`
- [ ] A real user signs in and sees their applications; the audit log shows the sign-in
- [ ] One synthetic or test document (in a test application, flagged and later archived) processes to `ready`
- [ ] `python -m app.cli verify-audit` reports `valid=True`
- [ ] Monitoring shows the new version healthy for 30 minutes; no new 5xx or error-log spike
- [ ] The nightly backup after the release completes and has a `MANIFEST`
