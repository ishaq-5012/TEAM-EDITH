# VerifyFlow AI — Phase 12 acceptance

Status as of 2026-10-23, on Windows 11 with Python 3.11.9 and Node 25. Everything below was run, not assumed.
Where something is partial or untested, this document says so.

## Command results

| Check | Command | Result |
| --- | --- | --- |
| Backend tests | `.\.venv\Scripts\python.exe -m pytest` (from `backend\`) | 521 collected: **520 passed, 1 skipped, 0 failed**. Skipped: `test_extraction.py:493` "Tesseract is not installed on this machine" |
| Backend lint | `.\.venv\Scripts\python.exe -m ruff check .` | `All checks passed!` |
| Migrations vs. models | `.\.venv\Scripts\python.exe -m alembic check` | `No new upgrade operations detected.` (database at `0011_synthetic_flag (head)`) |
| Frontend tests | `npx vitest run --maxWorkers=3 --minWorkers=1` (from `frontend\`) | 13 files, **111 passed, 0 failed** |
| Frontend typecheck | `npx tsc -b` | no errors |
| Frontend lint | `npx eslint .` | no findings |
| Production build | `npm run build` | `✓ built in 35.26s` |

Frontend tests on a busy machine: with the default worker count and dev servers running, some `findBy` waits time out
and different tests fail on each run. The same tests pass when run alone and in a full run with three workers. This
is a test-timing sensitivity, not a product defect.

## End-to-end synthetic workflow

`backend/tests/test_e2e_workflow.py` runs every step through the public HTTP API with three separately signed-in
users (author, approver, reviewer), on a database built from an empty file by the real migrations. **It passes.**

| # | Step | What the test checks |
| --- | --- | --- |
| 1 | Authenticate | Anonymous request is 401; each user gets a session and CSRF token |
| 2 | Create an application | 201, owned by the reviewer |
| 3 | Upload two synthetic documents | 201 each, SHA-256 recorded, both reach `ready` |
| 4 | Extract fields | Raw and normalized values, page number and bounding box for each field |
| 5 | Compare fields across documents | Near-miss name → `review` (`near_match`); different dates of birth → `fail` |
| 6 | Traceable compliance finding | Run summary has 1 fail and 1 review; the failing result names its rule version and carries a trace containing the input value; reproduction is identical |
| 7 | Uncertain finding to human review | An `uncertain` review item exists next to the `failure` item; the reviewer assigns it to themself |
| 8 | Correct a value with a reason | Before/after and the original extraction are recorded; the raw value is unchanged and the effective value is the correction |
| 9 | New validation run | The correction revalidates automatically; a further manual run also succeeds |
| 10 | Old and new results linked | First run unchanged (still 1 fail) and points to its successor; the new run passes; run list order and review history (`opened → field_corrected → revalidated`) are correct |
| 11 | Trust status | File integrity `verified`, recorded hash = observed hash; an unsigned PDF is not reported as signature-verified |
| 12 | Audit trail | Login, creation, upload, correction, validation and trust events present; hash chain valid; reviewers can't read the audit log |
| 13 | Dashboard metrics | 1 application, 2 documents, 3 runs (2 manual, 1 correction), backlog 1 uncertain item, 1 correction |

## Security and resilience checks

| Area | Tests | Result |
| --- | --- | --- |
| Authentication and authorization | `test_auth.py`, `test_users_rbac.py` (role matrix, anonymous rejected everywhere, denials audited) | pass |
| Malicious and malformed uploads | `test_documents.py`, `test_storage_and_system.py` (disguised types, JavaScript actions, encryption, oversize, chunked without length, empty, page limits) | pass |
| Path traversal | `test_security_boundaries.py`: traversal in filenames (stored as a display name only, generated storage key, file stays under the storage root), traversal in URL ids; `test_storage_and_system.py`: storage keys | pass |
| Document prompt injection | `test_ai.py::test_instructions_inside_documents_cannot_change_behaviour`, citation verification, content guard | pass |
| SQL and input validation | `test_security_boundaries.py`: six SQL/LIKE payloads across applications, reviews and audit search; length, type, range and malformed-JSON limits; `test_insights.py`: CSV formula injection in exports | pass |
| Cross-user data leakage | `test_security_boundaries.py::test_no_endpoint_leaks_another_users_application` (11 read endpoints and 3 write endpoints, plus lists, trust overview, insights scope, audit, exports); per-module isolation tests | pass |
| CSRF | `test_auth.py`: missing header, another session's token, forged cookie, cross-site Origin; uploads need the token | pass |
| Audit tampering | `test_audit.py`: ORM guard, database trigger against raw SQL, tamper and truncation detection, concurrent appends; `test_security_boundaries.py`: no API to create, change or delete events | pass |
| Invalid rule definitions | `test_rules_engine.py`, `test_rules_api.py`; `test_security_boundaries.py` checks seven single-defect definitions (unknown field, non-allowlisted operator, wrong value type, empty group, unknown severity, expression string, unknown policy) and confirms nothing is stored | pass |
| Incorrect source references | `test_security_boundaries.py`: corrections naming another application's field, a field on another document, or non-existent ids are refused and nothing is recorded; `test_ai.py`: hallucinated and foreign citations are rejected | pass |
| External AI provider outage | `test_ai.py::test_provider_outage_degrades_ai_only` (new): unreachable provider gives a bounded number of attempts, deterministic fallback, degraded health; validation and review still work. Plus timeouts, rate limits, auth errors, malformed/empty/refused output | pass |
| Concurrency and duplicates | `test_security_boundaries.py`: four simultaneous identical uploads store one document and one file; three simultaneous validation runs all complete. `test_review.py`: optimistic locking, database-level races, idempotent request ids. `test_extraction.py`: one active job per document | pass |
| Migrations from a fresh database | Every test builds its database from an empty file with `alembic upgrade head`; `test_security_boundaries.py` checks the schema matches the models, downgrades to empty and upgrades again; `test_migrations.py` covers data conversion and the SQLite cascade regression | pass |
| Responsive UI | Browser sweep of all 13 routes at 375 px and 768 px (Phase 11): no page-level horizontal scroll after fixing one row; tap targets ≥ 24 px; `motion.test.tsx` checks tables scroll in their container | pass (manual sweep + static check; no automated browser test) |
| Reduced motion | `motion.test.tsx` (new): with the preference set, the dialog jumps straight to its end state with no intermediate frames (the same check catches 9 intermediate frames when the preference is off); CSS stops transitions, shimmer and press movement | pass |

## The twelve innovations

| # | Innovation | Implementation | Tests | Status |
| --- | --- | --- | --- | --- |
| 1 | Cross-document reasoning | `app/evidence/` (comparators, engine), `evidence_service`, Evidence graph and list | `test_evidence.py`, `test_comparators.py`, e2e step 5 | Complete. Pairwise within a comparison group; cross-group reasoning needs both keys in one group |
| 2 | Rule-to-evidence traceability | Per-leaf traces in `rules/engine.py`, stored on each `RuleResult`; `TraceView` | `test_rules_engine::trace_records_provenance_for_every_leaf`, `test_rules_api::validation_run_traceable_and_reproducible`, e2e step 6 | Complete |
| 3 | Uncertainty-aware validation | Three-valued logic, missing-data and low-confidence policies, OCR quality, stale evidence | `test_rules_engine.py` (policies, three-valued logic), `test_evidence.py` (OCR noise, ambiguity) | Complete |
| 4 | Human-in-the-loop resolution | `review_service`: queue, assignment, decisions with reasons, escalation, document requests, corrections | `test_review.py`, e2e steps 7–8 | Complete. No notifications for assignment or escalation |
| 5 | Modular compliance rules | Declarative JSON rules with allowlisted operators only (`rules/schema.py`) | `test_rules_engine::every_allowlisted_operator_is_tested`, invalid-rule tests | Complete. No cross-field arithmetic by design |
| 6 | Trust-aware authentication | `app/trust/`: hash re-check, pyHanko signatures, configured anchors, revocation, timestamps, registry connectors | `test_trust_engine.py`, `test_trust_api.py`, e2e step 11 | Complete for PDFs. Only synthetic and generic HTTP registry connectors exist; no real government registry |
| 7 | Contradiction impact analysis | `evidence/priority.py`: documented score from severity, outcome, evidence quality, breadth and impact | `test_evidence.py` (factor sums) | **Partial.** The "impact" factor counts impact labels configured on the comparison group. It isn't derived from the published rules that read the contradicting fields. Corrections do compute affected rules (`review_service.affected_rules`), but evidence findings don't show them |
| 8 | Versioned, effective-dated rules | Immutable versions, draft → pending → published → retired, four-eyes approval, effective windows | `test_rules_api.py` (lifecycle, boundaries, clashes, immutability) | Complete. Needs two users with `rules:publish` |
| 9 | What-if rule simulation | `POST /rules/simulate`, read-only, before/after view | `test_rules_api::simulation_is_isolated`, `simulating_a_draft_version_and_invalid_proposals` | Complete. At most 50 applications per request |
| 10 | Evidence-grounded AI explanations | `ai_service`, `assist/`, guarded gateway; citations verified against the database; deterministic fallback | `test_ai.py` (19 + 1 new) | Complete in no-AI mode and against a mocked Anthropic SDK. **Never exercised against the real API** |
| 11 | Extraction provenance and source highlighting | Raw/normalized values, page coordinates, Extraction Inspector, review split pane | `test_extraction.py` (coordinates, rotation, OCR), `inspector.test.tsx`, e2e step 4 | Complete. Baseline extractor handles "Label: value" layouts only |
| 12 | Reproducible runs and append-only audit | Stored rule definitions and input snapshot per run, reproduction endpoint; hash-chained audit with trigger | `test_rules_api.py`, `test_audit.py`, e2e steps 6, 10, 12 | Complete |

## Seven modules

All seven routes render real pages backed by the API (Command Center, Application Workspace, Evidence Intelligence
Graph, Compliance Studio, Review and Resolution Center, Trust and Authentication Center, Governance and Insights).
`features/modules/PlannedModulePage.tsx` is still in the code as a fallback for modules marked "planned", but no
module has that status, so it is never shown.

## Changes made in Phase 12

- `backend/requirements.txt`: `httpx` was imported at runtime by `app/trust/registries.py` but listed only as a dev
  dependency. A clean production install failed at startup with `ModuleNotFoundError`. It is now a runtime dependency.
- `backend/.venv` recreated with Python 3.11.9 (the old one pointed to another machine's Python).
  `backend/.env` and `.claude/launch.json` now use `E:/sih 2` paths.
- New tests: `backend/tests/test_e2e_workflow.py`, `backend/tests/test_security_boundaries.py`,
  `test_ai.py::test_provider_outage_degrades_ai_only`, `frontend/src/test/motion.test.tsx`.
- Docs: `docs/ARCHITECTURE.md` (new), this file (new), `docs/API.md` (contract guarantees), README (status,
  setup on a new machine, troubleshooting).

No application logic changed in Phase 12: every new test passed against the existing code, apart from mistakes in
the tests themselves.

## Remaining risks

1. ~~PostgreSQL isn't ready.~~ Resolved in Phase 13: `psycopg` added, migration `0011` fixed, and the full suite
   passes on PostgreSQL 16 (see [DEPLOYMENT.md](DEPLOYMENT.md)).
2. ~~No durable job queue.~~ Resolved in Phase 13: worker mode runs jobs from the database and recovers interrupted
   ones.
3. **Contradiction impact is label-based** (innovation 7, above).
4. **Contracts are kept in sync by hand.** `frontend/src/lib/types.ts` mirrors `backend/app/schemas/` with no
   generation or automated comparison. A drift would show up only through a failing test or at runtime.
5. **No automated browser end-to-end test.** The workflow test is API-level. The UI is covered by component tests
   and the manual phone/tablet sweep, not by a browser test runner.
6. **AI has only been tested against mocks.** The Anthropic adapter is verified against a mocked SDK client, and the
   content guard is pattern-based.
7. **OCR is untested on this machine.** Tesseract isn't installed, so the real-OCR test is skipped here.
8. **SQLite single-writer.** Concurrency tests pass on SQLite because writes serialize; heavier load in
   development can still show `database is locked`.
9. **Authentication gaps.** No MFA, SSO or self-service password reset; per-IP throttling needs the real client IP
   behind a proxy.
10. **Not under version control.** The project folder isn't a git repository, so none of this work is committed or
    reviewable as a diff.
