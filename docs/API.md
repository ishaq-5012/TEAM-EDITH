# VerifyFlow AI — API reference (Phase 13)

Base path: `/api/v1`. Interactive OpenAPI docs: `http://127.0.0.1:8000/api/docs`.
Frontend contracts live in `frontend/src/lib/types.ts` and must change together with `backend/app/schemas/`.

## Authentication model

Browser sessions are **server-side** and carried in cookies. There are no bearer tokens: an `Authorization` header is
ignored.

| Cookie | Flags | Purpose |
|---|---|---|
| `__Host-vf_session` | HttpOnly, Secure, SameSite=Lax, Path=/ | Random 256-bit session token. Only its SHA-256 hash is stored. JavaScript cannot read it. |
| `__Host-vf_csrf` | Secure, SameSite=Strict, Path=/, **readable** | CSRF synchronizer token. Its hash is stored on the session. |

(With `VERIFYFLOW_COOKIE_SECURE=false` the names lose the `__Host-` prefix. That setting is refused in production.)

**Session lifetime:** a session ends after `VERIFYFLOW_SESSION_IDLE_MINUTES` of inactivity (default 30), and
unconditionally after `VERIFYFLOW_SESSION_ABSOLUTE_HOURS` (default 12). Every authenticated response carries
`X-Session-Expires` (ISO-8601), the moment the session will end without further activity. Logout, password change
(other sessions), password reset, role change, deactivation and admin revocation all take effect immediately on
the server.

**CSRF:** every `POST`/`PUT`/`PATCH`/`DELETE` on an authenticated endpoint must send `X-CSRF-Token: <value of the
CSRF cookie>`. The server compares the value against the hash stored on *that* session, so a token from another
session or a forged cookie is rejected with **403 `csrf_failed`** (audited as `security.csrf_rejected`).
Independently, any state-changing request (login included) whose `Origin` header is neither this server nor a
configured `VERIFYFLOW_CORS_ORIGINS` entry is rejected with **403 `origin_rejected`**.

**Sign-in throttling:** failed attempts are counted per submitted email and per client IP over
`VERIFYFLOW_LOGIN_WINDOW_MINUTES`. Unknown and real accounts are treated identically, so throttling can't be used to
discover accounts. Exceeding a limit returns **429 `too_many_attempts`** with a retry time. A successful sign-in
resets the email counter, and an admin password reset clears it.

## Conventions

- **Errors:** `{ "error": { "code", "message", "details" } }`.
  - `unauthorized` (401): no session cookie.
  - `session_expired` (401): the cookie was valid once, but the session ended.
  - `invalid_credentials` (401).
  - `forbidden` (403): role lacks the permission. Audited as `security.permission_denied`.
  - `csrf_failed` / `origin_rejected` (403).
  - `not_found` (404). Also returned for records owned by someone else, so their existence isn't revealed.
  - `conflict` (409), `validation_error` (422), `too_many_attempts` (429), `internal_error` (500).
  - Upload-specific codes are listed under [Applications and documents](#applications-and-documents).
- **Pagination:** `?limit=&offset=` → `{ items, total, limit, offset }`.
- **Request IDs:** send `X-Request-ID` (8–64 chars, `[A-Za-z0-9-]`) or one is generated. It is echoed in the
  response and stored on audit events.

### Contract guarantees checked in Phase 12

Pinned by `tests/test_e2e_workflow.py` and `tests/test_security_boundaries.py`:

- Identifiers that contain path separators or traversal sequences return 404 or 422 and never reach storage.
  Upload filenames are reduced to a display name; storage keys are generated. A name with no extension left after
  sanitizing is refused with `415 extension_mismatch`.
- Text filters (`q`) are bound parameters with `LIKE` wildcards escaped. SQL fragments match nothing and change
  nothing.
- Query bounds are enforced with 422: `limit` within each endpoint's range (1–100 for applications, 1–200 for audit
  events), `offset` ≥ 0, `q` ≤ 100 characters, and enumerated filters only.
- Every per-application endpoint (documents, download, extraction, page images, evidence, validation runs and their
  reproduction, verifications) returns 404 to a user without access. List endpoints return empty results, and
  insights report a scope of 0.
- A correction must name a field of a document in the review item's own application; anything else is refused and
  nothing is recorded.
- Audit events have no create, update or delete endpoint (`405`/`404`).
- Concurrent uploads of identical content store exactly one document (`201` once, `409 duplicate_document` for the
  rest). Concurrent validation runs each complete and are each stored.

## Endpoints

| Method | Path | Requires | Description |
|---|---|---|---|
| GET | `/health` | public | Liveness and DB probe. 503 when the DB is unreachable. |
| GET | `/health/ready` | public | Readiness: `database`, `migrations` (`ok`/`behind`), `storage` (writable), and `processing` (`mode`, `queued`, `oldest_queued_seconds`, `stale_running`; counts only). 503 unless database, migrations and storage are all `ok`. |
| GET | `/system/capabilities` | `system:read` | Runtime capabilities with honest availability. |
| POST | `/auth/login` | public (Origin-checked) | `{email, password}` → `{user: Me, csrf_token}` and sets both cookies. Replaces any session the browser already had. |
| POST | `/auth/logout` | session + CSRF | Revokes the session server-side and clears the cookies. 204. |
| GET | `/auth/me` | session | Current user, permission list and `session` (`id`, `created_at`, `expires_at`, `idle_expires_at`, `idle_timeout_minutes`). |
| POST | `/auth/change-password` | session + CSRF | `{current_password, new_password}` → 204. Keeps this session, revokes all others. |
| GET | `/auth/sessions` | session | Your active sessions (`current: true` marks this one). |
| DELETE | `/auth/sessions/{id}` | session + CSRF | Revoke one of **your** sessions (any session with `sessions:manage`). Others' sessions → 404. |
| POST | `/auth/sessions/revoke-others` | session + CSRF | Sign out all your other sessions → `{revoked}`. |
| GET | `/users` | `users:read` | List users. |
| GET | `/users/{id}` | own record, or `users:read` | Others' records → 404 without the permission. |
| POST | `/users` | `users:manage` | `{email, full_name, role, password}` → 201. |
| PATCH | `/users/{id}` | `users:manage` | `{full_name?, role?, is_active?, reason}`. Role/status changes end the user's sessions. Cannot remove the last active admin. |
| POST | `/users/{id}/reset-password` | `users:manage` | `{new_password, reason}` → 204. Ends sessions, clears sign-in throttling. |
| GET | `/users/{id}/sessions` | `sessions:manage` | A user's active sessions. |
| POST | `/users/{id}/revoke-sessions` | `sessions:manage` | `{reason}` → `{revoked}`. Signs the user out everywhere. |
| GET | `/audit/events` | `audit:read` | Filter by `action` (exact, or a prefix ending in `.` such as `rule.`), `entity_type`, `entity_id`, `actor_id`, `outcome`, `from` / `to` (UTC dates, inclusive) and `q` (summary or actor email). Newest first; `limit` ≤ 200 and `offset`. |
| GET | `/audit/actions` | `audit:read` | Distinct recorded actions, for filter menus. |
| GET | `/audit/verify` | `audit:read` | Re-hashes the full chain → `{valid, checked, first_invalid_seq, reason, head_hash}`. |

## Roles and permissions

| Permission | admin | compliance_manager | reviewer | auditor |
|---|:-:|:-:|:-:|:-:|
| users:manage | ✓ | | | |
| sessions:manage | ✓ | | | |
| users:read | ✓ | ✓ | | ✓ |
| audit:read | ✓ | ✓ | | ✓ |
| applications:read (own / assigned) | ✓ | ✓ | ✓ | ✓ |
| applications:read_all (regardless of owner) | ✓ | ✓ | | ✓ |
| applications:write | ✓ | ✓ | ✓ | |
| documents:upload | ✓ | ✓ | ✓ | |
| documents:read | ✓ | ✓ | ✓ | ✓ |
| rules:read | ✓ | ✓ | ✓ | ✓ |
| rules:manage / rules:publish | ✓ | ✓ | | |
| validation:run | ✓ | ✓ | ✓ | |
| review:resolve | ✓ | ✓ | ✓ | |
| system:read | ✓ | ✓ | ✓ | ✓ |
| exports:create | ✓ | ✓ | | ✓ |
| exports:sensitive (document values) | ✓ | ✓ | | |

**Ownership (resource-level authorization):** `app/core/authz.py` gives every user-scoped record a single policy.
Access is allowed if the user owns the record or is assigned to it, or holds the record type's override permission
(`sessions:manage` for sessions, `users:read` for user records, `applications:read_all` for applications once that
module exists). Otherwise the API answers 404. Application, document and review records will implement the same
`OwnedResource` protocol when those modules ship.

## Audited security events

`auth.login`, `auth.login_failed` (with reason: `unknown_account` / `wrong_password` / `inactive_account`; the
client always sees the same message), `auth.login_throttled`, `auth.logout`, `auth.session_revoked`,
`auth.sessions_revoked`, `auth.password_changed`, `auth.password_change_failed`, `security.csrf_rejected`,
`security.permission_denied`, `user.created`, `user.updated` (before/after + reason), `user.password_reset`,
`user.bootstrap_admin`.

## Applications and documents

All endpoints are under `/api/v1/applications` and need a session. State-changing calls also need CSRF.

### Access rules (enforced on the server for every call)

| Who | Read | Edit details / upload / retry | Manage members, archive / restore |
|---|:-:|:-:|:-:|
| Owner (creator) | ✓ | ✓ | ✓ |
| Member: `contributor` | ✓ | ✓ | |
| Member: `viewer` | ✓ | | |
| Role with `applications:read_all` (compliance manager, auditor, admin) | ✓ | needs `applications:write` too | needs `applications:write` too |
| Anyone else | 404 | 404 | 404 |

Editing additionally requires the `applications:write` permission, so auditors are always read-only. Someone who can
read but not edit gets 403. Anyone who can't read gets 404, so the API never confirms that someone else's
application exists. Every detail response includes `permissions`
(`can_edit`, `can_upload`, `can_manage_members`, `allowed_actions`), computed by the server. The UI uses these to
decide which controls to show.

### Lifecycle

```
draft ──upload──▶ processing ──all documents processed──▶ needs_review ──complete──▶ completed
  ▲                    ▲                                        │  ▲                      │
  │                    └────────────── upload / retry ──────────┘  └────────reopen────────┘
  └─ any non-archived status ──archive──▶ archived ──restore──▶ previous status
```

- `processing` and `needs_review` are set automatically. Uploading or retrying puts the application into
  `processing`, and once nothing is queued or processing it moves to `needs_review`.
- `complete` requires at least one document and nothing still processing.
- `archive` requires nothing still processing.
- Completed applications don't accept uploads (reopen first). Archived applications are read-only (restore first).
- Every transition requires a `reason` and is audited.

### Endpoints

| Method | Path | Requires | Description |
|---|---|---|---|
| GET | `/applications` | `applications:read` | Visible applications. Query: `status` (repeatable), `q` (title/reference/applicant, wildcards literal), `application_type`, `scope=all\|mine`, `sort=updated_desc\|created_desc\|reference_asc\|title_asc`, `limit` (1–100, default 25), `offset`. Returns `{items, total, limit, offset, application_types, can_create}`. Each item includes `document_count`. |
| POST | `/applications` | `applications:write` | `{title (3–200), application_type (2–60), applicant_name?, description? (≤5000)}` → 201 `ApplicationDetail`. The caller becomes the owner. The reference has the form `APP-YYYY-XXXXXX` (unambiguous alphabet). |
| GET | `/applications/upload-limits` | `applications:read` | `{max_upload_bytes, max_pdf_pages, max_documents_per_application, accepted: {mime: [extensions]}}` |
| GET | `/applications/{id}` | read access | `ApplicationDetail`: summary, `description`, `archived_at`, `members`, `document_status_counts`, `permissions`. |
| PATCH | `/applications/{id}` | edit access, not archived | Any of `title`, `application_type`, `applicant_name`, `description`. Only changed fields are recorded (before/after). No changes → 400 `no_changes`. |
| POST | `/applications/{id}/transitions` | edit access (archive/restore: manage access) | `{action: complete\|reopen\|archive\|restore, reason}`. Not allowed in the current state → 409 `invalid_transition`. |
| POST | `/applications/{id}/members` | manage access | `{email, role: contributor\|viewer}` → 201. 404 if there is no active user with that email. 409 for the owner, or if the user is already a member with that role. 400 `role_cannot_contribute` if the user's role is read-only. |
| DELETE | `/applications/{id}/members/{user_id}` | manage access | 204. |
| GET | `/applications/{id}/documents` | read access | `DocumentOut[]`, oldest first, each with `latest_job` and `can_retry`. |
| POST | `/applications/{id}/documents` | edit access | **multipart/form-data**: one `file` part plus an optional `document_type` (≤60 chars). Returns 201 `DocumentOut`. Processing starts in the background. |
| GET | `/applications/{id}/documents/{doc_id}` | read access | `DocumentDetail` = `DocumentOut` + `jobs` (every attempt, with `result.facts`, `result.findings`, `error_code`, `error_message`). A document from another application → 404. |
| GET | `/applications/{id}/documents/{doc_id}/content` | read access | Original bytes, after re-verifying their SHA-256. Headers: `Content-Disposition: attachment`, `Content-Type` = **detected** type, `Content-Security-Policy: default-src 'none'; sandbox`, `X-Content-Type-Options: nosniff`, `Cache-Control: private, no-store`, `X-Document-SHA256`. Audited (`document.downloaded`). |
| POST | `/applications/{id}/documents/{doc_id}/retry` | edit access, not archived | Re-queue processing for a `failed` document, or one whose job has been stuck longer than `VERIFYFLOW_PROCESSING_STALE_MINUTES` (the stuck job is marked `interrupted`). Otherwise 409 `retry_not_allowed`. |

`DocumentOut` fields: `id`, `application_id`, `original_filename` (sanitised, display only), `document_type`,
`declared_mime` (what the client claimed), `detected_mime` (from the file's bytes), `size_bytes`, `sha256`,
`page_count`, `status` (`queued|processing|ready|needs_review|failed`), `uploaded_by`, `created_at`, `updated_at`,
`latest_job`, `can_retry`. **Storage keys and filesystem paths are never returned.** Download URLs need an
authenticated session, so there are no permanent or public links.

### Upload validation

Checks run in this order, and nothing is committed until all of them pass. On any failure the stored bytes are
deleted and a `document.upload_rejected` (or `document.upload_failed`) audit event is written.

| Check | Failure |
|---|---|
| `Content-Length` present | 411 `length_required` (chunked uploads are refused) |
| `Content-Length` ≤ `max_upload_bytes` + multipart overhead, checked before the body is read | 413 `file_too_large` |
| `Content-Type: multipart/form-data` with a `file` part | 415 `unsupported_media_type`, 422 `file_required`, 400 `invalid_multipart` |
| Streaming size limit while writing to private storage (SHA-256 computed on the fly) | 413 `file_too_large`, 400 `empty_file` |
| Type from magic bytes: PDF, PNG, JPEG, TIFF only | 415 `unsupported_file_type` |
| Filename extension matches the detected type | 415 `extension_mismatch` (for example a PNG named `.pdf`, or no extension) |
| Declared MIME matches the detected type (`application/octet-stream` / empty count as undeclared) | 415 `mime_mismatch` |
| PDF parses, isn't encrypted, has between 1 and `max_pdf_pages` pages | 422 `pdf_invalid`, `pdf_encrypted`, `pdf_empty`, `pdf_too_many_pages` |
| Image decodes fully, within `max_image_pixels` (decompression-bomb guard) | 422 `image_invalid`, `image_too_large` |
| Not already in this application (same SHA-256) | 409 `duplicate_document` (the message names the existing file). The same file is allowed in other applications. |
| Application accepts uploads | 409 `application_archived`, `application_completed`, `document_limit_reached` |
| Storage writable | 503 `storage_unavailable` (no record is created; the details stay in the server log) |

### Processing (intake inspection + extraction)

A background job runs after each upload (and after a retry or reprocess). It's deterministic, uses no AI, and has
two steps: the intake inspection described below, then [extraction](#extraction).

- It re-verifies the stored file's SHA-256. A mismatch fails the job with `integrity_mismatch`.
- **PDFs:** page count, which pages have no text layer, embedded files, JavaScript actions, document metadata,
  whether MuPDF had to repair the structure, and any objects it couldn't read.
- **Images:** format, dimensions, colour mode, frame count.
- **Status:**
  - `needs_review` if the PDF contains JavaScript, embedded files, structural repair, or objects that couldn't be
    read.
  - `ready` otherwise. "OCR required" is an informational finding, not a problem.
  - `failed`, with `error_code` and `error_message`, if inspection itself fails. Failed documents can be retried.

Jobs run in-process after the response is sent. This isn't a durable queue: a job interrupted by a restart is
detected as stale and can be retried.

### Audited application and document events

`application.created`, `application.updated` (before/after), `application.completed`, `application.reopened`,
`application.archived`, `application.restored`, `application.member_added`, `application.member_updated`,
`application.member_removed`, `document.uploaded` (sha256, size, detected type, pages), `document.upload_rejected`
(reason code), `document.upload_failed`, `document.processed` (status, attempt, error code),
`document.processing_retried`, `document.downloaded`, `document.integrity_failed`. All are recorded with
`entity_type=application` and `entity_id=<application id>`, so `GET /audit/events?entity_id=<id>` returns an
application's complete history.

## Extraction

Endpoints are under `/api/v1/applications/{application_id}/documents/{document_id}`. Reading needs
`documents:read` plus read access to the application. Corrections and reprocessing need edit access and CSRF, and
aren't possible on archived or completed applications.

| Method | Path | Description |
|---|---|---|
| GET | `/extraction` | The current run: `run`, `extractor` (name, version, kind, **limitations**), `pages`, `fields`, `can_correct`, `can_reprocess`. Returns 404 `not_extracted` if the document has never been extracted (for example, it was uploaded before extraction existed). |
| GET | `/extraction/runs` | Every run, newest first. Runs are never deleted. |
| GET | `/extraction/runs/{run_id}` | The full view of any historical run, for reproducibility. |
| GET | `/pages/{n}/text` | `{raw_text, normalized_text, text_source}`. Raw text is exactly as produced by the text layer or OCR. Normalized text only collapses whitespace. |
| GET | `/pages/{n}/image?scale=0.25..3` | PNG of the page **as displayed** (rotation and EXIF applied), re-verified against the document's SHA-256. |
| POST | `/reprocess` | `{force: bool}` → 202. Queues inspection and extraction. Without `force`, an existing run with the same idempotency key is reused. 409 `already_processing` if a job is queued or running. |
| POST | `/extraction/fields/{field_id}/corrections` | `{value, reason}` → 201. Appends a correction to a field of the **current** run (409 `stale_field` for an older run). The value is validated with the field's normalizer. 422 `invalid_value` for an invalid value, or an ambiguous date: enter `YYYY-MM-DD`. |

### Pages

- `text_source`: `text_layer` | `ocr` | `none`
- `text_layer_quality`: `good` | `sparse` | `unusable` (garbled encoding; ignored) | `none` | `n/a` (images)
- `ocr_status`:
  - `not_needed`
  - `completed`
  - `low_confidence` (mean word confidence below 60)
  - `unavailable` (no OCR engine on the server)
  - `failed`
  - `skipped_limit` (beyond `VERIFYFLOW_OCR_MAX_PAGES`)

  Each non-OK state also adds an entry to the page's `warnings`.
- A page is sent to OCR when its text layer is `none` or `unusable`. `sparse` pages keep their text layer, with a
  warning.
- A run is `partial` if any page ended with no readable text. Fields on those pages show as `missing`, flagged
  `pages_without_text`.

### Coordinates

A field's `bbox` is `[x0, y0, x1, y1]` in the **displayed** space of `page_number`:
- origin top-left, y pointing down;
- PDF `/Rotate` applied, so a 90°-rotated A4 page is 842 × 595;
- units are PDF points for PDFs and pixels for images, given by each page's `units`.

`/pages/{n}/image` renders the same space, so a box maps to the image as percentages of `width` and `height`.
Tests check this by measuring ink inside stored boxes on rendered pages, at 0°, 90°, 180° and 270°, and for
OCR-sourced words.

### Fields

Each configured field is always present in a run:
- `status`:
  - `found`
  - `missing` (never guessed)
  - `invalid` (found, but fails validation; `normalized_value` is null and `normalization_note` says why)
  - `ambiguous` (for example, day and month could be swapped; normalized according to the configured
    `date_order`)
- `raw_value`: the source characters (multi-line for addresses).
- `normalized_value`, plus `normalized_data` (the strict schema dump: `{full}`, `{iso}`, `{value}` or `{lines}`).
- `method` (`text_layer_rule` | `ocr_rule`), `matched_label`, `page_number`, `bbox`.
- `confidence`: a heuristic score, not a calibrated probability.
- `quality_flags`:
  - `ocr_source`, `low_ocr_confidence`
  - `possible_ocr_confusion` (O/0, I/l/1 next to digits, flagged and **never auto-corrected**)
  - `ambiguous_day_month`
  - `conflicting_candidates` (other values are listed in `alternatives`)
  - `pages_without_text`, `required_missing`, `address_truncated`
- `corrections`, `effective_value` and `effective_source` (`correction` | `normalized` | `raw` | `none`).
- `correction_based_on_other_value`: true when the latest correction was made against a different extracted
  value than this run produced.

### Field definitions

Field definitions are configurable in `app/extraction/field_definitions.json`, or at
`VERIFYFLOW_FIELD_DEFINITIONS_PATH`. They're validated strictly: unknown keys, duplicate keys or labels, options
that don't apply to the field type, and invalid regexes are all rejected. Field types are `name`, `date`,
`identifier`, `address` and `document_number`, each with its own normalizer. There is no universal normalizer, and
raw values are never overwritten.

### Integrity, idempotency and concurrency

- **One active job per document.** A partial unique index on `processing_jobs(document_id)` allows at most one
  queued or running job, so concurrent reprocess requests get 409.
- **Claiming.** A worker claims a job with `UPDATE … WHERE status='queued'`, so running the same job twice is a
  no-op.
- **Committing results.** Results (run, pages, fields) are committed in one transaction, and only if the job is
  still `running`. A superseded job (for example, one replaced by a stale-retry) discards its results.
- **Reuse.** The idempotency key is `sha256(file hash | extractor@version | definitions hash | OCR engine)`.
  Reprocess without `force` reuses a matching run. Installing an OCR engine changes the key, so a later
  reprocess really re-extracts.
- **Current run.** A partial unique index allows at most one current run per document.
- **Immutable records.** Extracted pages and fields are immutable (ORM guards). Corrections are append-only, and
  keyed by document and field so they survive reprocessing.

### Audited events

`document.reprocess_requested`, `document.processed` (with `extraction_run_id` and `reused_run`), and
`extraction.field_corrected` (`before`, `after`, `original_extracted`, `reason`).

## Evidence Intelligence Graph (cross-document reasoning)

Endpoints are under `/api/v1/applications/{application_id}/evidence`. Viewing needs `documents:read` plus read
access to the application. Running an analysis needs `validation:run` plus edit access, and isn't possible on
archived applications.

| Method | Path | Description |
|---|---|---|
| GET | `` (root) | The current analysis: `analysis` (meta), `stale`, `can_analyze`, `findings[]`. Returns 404 `not_analyzed` before the first analysis. |
| POST | `/analyses` | `{force: bool}`. Runs the deterministic analysis → 201. If the inputs are identical to the current analysis it returns 200 with `reused: true`, unless `force` is set. Returns 409 `no_documents` if there's nothing to analyse. |
| GET | `/analyses` | Every analysis, newest first. Exactly one is current. |
| GET | `/analyses/{analysis_id}` | Any historical analysis exactly as stored. |

### Data model

- **Analysis**
  - Records the comparator and engine version, config version and hash, document count and summary.
  - Records `input_fingerprint`, the SHA-256 of every input value snapshot plus the comparator version and config
    hash.
  - `stale` is true when the fingerprint computed now differs from the stored one. That happens after new
    documents, re-extraction, corrections, config changes or engine updates.
- **Finding** (one per comparison group):
  - `outcome`, `severity` and `evidence_quality` are **independent dimensions**.
  - `priority_score` and `priority_factors`.
  - `coverage`: documents, values present, missing, invalid, not extracted, and the minimum needed.
  - `explanation`.
- **Evidence reference.** An immutable snapshot of one document's value:
  - `document_id`, `extraction_run_id`, `extracted_field_id`, `correction_id`;
  - the raw, normalized and effective (compared) value, and `value_source` (`correction` | `extracted` | `none`);
  - `page_number`, `bbox`, plus `page_width` / `page_height` in the same displayed space;
  - quality flags, `evidence_quality`, `usable`.
- **Field relationship.** A comparison between a source reference and a target reference:
  - `result`, `method`, `reason`, `details` (the normalizations applied, distances, tolerances, differing tokens or
    positions), `evidence_quality` and `explanation`.

Findings, references and relationships are immutable (ORM guards). Their provenance foreign keys (document,
extraction run, field, correction) use RESTRICT.

### Comparison groups

Comparison groups are configured in `app/evidence/comparison_config.json`, or at
`VERIFYFLOW_COMPARISON_CONFIG_PATH`. The config is validated strictly: unknown options are rejected, and a field
can belong to only one group. Each group has `fields` (extracted field keys pooled together), a `comparator`, a
`severity`, `impacts` (downstream decisions) and `min_values` (default 2).

| Comparator | Passes when | Review when | Fails when |
|---|---|---|---|
| `name` | Equal, or equal after enabled normalizations (`ignore_case`, `ignore_diacritics`, `ignore_punctuation`, and `allow_token_reorder` if enabled) | ≤1–2 character difference, same words in a different order (not allowed), shared words with others differing (no aliases such as Bob/Robert), possible initials | No shared words and not a near miss |
| `date` | Equal, or within `tolerance_days` | Day and month swapped | Otherwise |
| `identifier`, `document_number` | Equal, or equal ignoring separators (only if `ignore_separators`) | Differences only at OCR look-alike positions (O/0, I/1, L/1, S/5, B/8, Z/2, G/6), or only separators differ and ignoring them isn't configured | Otherwise |
| `address` | Equal after enabled case and punctuation normalization and **configured** `abbreviations` only | ≥60% word overlap | Otherwise |
| `text` (configurable fields) | Equal, or equal after `ignore_case` / `ignore_whitespace` | — | Otherwise |

### Outcome rules (engine)

1. Either side has no usable value (missing, invalid or not extracted) → `insufficient`, with no evidence quality
   claimed.
2. Values pass, but at least one was `ambiguous` when extracted and isn't confirmed → `review`
   (`ambiguous_input`).
3. Values fail, but at least one is **low** quality (low OCR confidence, possible OCR confusion, ambiguous, or a
   score below 0.6) → `review` (`low_quality_evidence`). A confirmed `fail` needs both values to be at least
   medium quality.
4. Otherwise the comparator's result stands.

A finding is `insufficient` when fewer than `min_values` documents have a usable value. Otherwise it's `fail` if
any relationship fails, `review` if any needs review, and `pass` if not. Documents without a value are listed as
gaps and linked to the first usable value. They never turn agreement into a failure. When no document has a value,
no relationships are created.

Evidence quality: **high** means a human correction, or a clean text-layer value with a score of at least 0.8.
**Medium** means OCR without flags, or a score between 0.6 and 0.8. **Low** covers everything flagged above.

### Priority (contradiction impact analysis)

The priority score runs from 0 to 100, is deterministic, and is shown with every factor. It is not a compliance
decision.

| Factor | Contribution |
|---|---|
| Severity | critical 40 · high 30 · medium 20 · low 10 |
| Outcome | fail 30 · review 20 · insufficient 10 · pass 0 |
| Evidence quality | high 10 · medium 6 · low 2 · none 0 |
| Breadth | 5 per document in a disagreement beyond the first, max 10 |
| Impact | 5 per configured downstream decision, max 10 |

Passing findings score 0, and their factors are still returned.

### Audited events

`evidence.analyzed`: analysis id, input fingerprint, config hash, comparator version, summary, and whether it was
forced.

## Compliance Studio: declarative rules (Phase 6)

Rules are **data, never code**. A rule definition is a JSON document validated by strict Pydantic models
(`app/rules/schema.py`). There is no expression parser, no `eval`, no user-supplied regular expressions and no SQL.
The only behaviour is the allowlisted operators, implemented in `app/rules/engine.py` (`rules-engine/1.0`).

> A passing rule is **not** a legal or regulatory determination. Every rule list, rule, validation run and
> simulation response carries this disclaimer. Rules reflect their documented source and owner.

### Definition

```json
{
  "condition": {"all": [
    {"field": "extracted.date_of_birth", "op": "age_years_at_least", "value": 18, "quantifier": "all"},
    {"not": {"field": "evidence.person_name.outcome", "op": "eq", "value": "fail"}}
  ]},
  "applies_when": {"field": "application.application_type", "op": "in", "value": ["kyc", "loan"]},
  "severity": "high",
  "on_violation": "fail",
  "missing_data_policy": "insufficient",
  "low_confidence_policy": "review",
  "pass_message": "",
  "fail_message": "Applicant under 18"
}
```

- **Groups:** `all` (every child), `any` (at least one), `not` (one child). Depth ≤ 6, at most 50 leaves.
- **Fields** (`GET /rules/catalog`, derived from configuration): `extracted.<field_key>` (one value per document),
  `evidence.<group>.outcome` (current evidence finding), `application.application_type`,
  `application.document_count`.
- **Quantifier** (extracted fields only): `all` means every document that has a usable value; `any` means at
  least one.
- **Operators per type** (value shape in brackets):

| Type | Operators |
|---|---|
| text | `eq` `ne` [value] · `in` `not_in` [list] · `contains` `starts_with` `ends_with` [value] · `exists` `not_exists` [none] |
| date | `eq` `ne` `before` `after` `on_or_before` `on_or_after` [YYYY-MM-DD] · `between` [[from, to], inclusive] · `before_evaluation_date` `after_evaluation_date` [± days offset] · `age_years_at_least` `age_years_at_most` [whole years, birthday-exact] · `exists` `not_exists` |
| number | `eq` `ne` `gt` `gte` `lt` `lte` [number] · `between` [[from, to], inclusive] · `exists` `not_exists` |
| outcome | `eq` `ne` [pass / fail / review / insufficient] · `in` `not_in` [list] · `exists` `not_exists` |

Text comparison is exact and case-sensitive on the already-normalized extracted value (field normalization happens
at extraction). No other equivalence is assumed.

### Evaluation (three-valued, uncertainty-aware)

A leaf is **true**, **false** or **unknown** (no usable value); `all`/`any`/`not` use three-valued (Kleene) logic.
A value is usable when it was extracted with status `found` or `ambiguous`, or was corrected by a person. A leaf is
**low confidence** when any observation it used is low quality (for example low OCR confidence), or when the
evidence analysis is stale.

| Situation | Outcome |
|---|---|
| `applies_when` is false | `not_applicable` |
| condition unknown (data missing) | `missing_data_policy`: `insufficient`, `review`, `pass`, or `fail` (meaning `on_violation`) |
| low-confidence input and policy is not `evaluate` | `review` or `insufficient`; `details.would_have_been` records the result confident inputs would give |
| condition true | `pass` |
| condition false | `on_violation` (`fail` or `review`) |

Every result carries a **trace**: one entry per evaluated leaf, with the field, operator, expected value, result
and the exact observations. Each extracted observation has the document id and name, extraction run, field id,
correction id, raw and normalized value, page, bounding box, quality and its own result. Evidence observations
carry the analysis and finding ids.

### Versions, lifecycle and approval

```
draft ──submit──▶ pending_approval ──approve──▶ published ──retire──▶ retired
                         └──────reject──────▶ rejected
```

- One open draft and one pending version per rule (enforced by the database). Only drafts can be edited.
- **Immutable versions.** Once submitted, a version's definition, dates, source and change summary can't change.
  The API answers 409 `immutable`, and an ORM guard also blocks updates and deletes. Each version stores a SHA-256
  `content_hash`.
- **Submit** requires `rules:manage`, a `source_reference`, a `change_summary`, and every synthetic test case to
  pass (409 `tests_failing`, with the failing cases in `details`).
- **Approve and reject** require `rules:publish` and a note. They must be done by someone who neither authored nor
  submitted the version (403 `four_eyes_required`). Approval is refused if another published version of the rule
  already starts on the same date (409 `effective_date_clash`).
- **Retire** requires `rules:publish` and a reason.
- **Effective dates.** `effective_from` is inclusive and `effective_to` exclusive. On date *D* the version in force
  is the published version with the latest `effective_from ≤ D`. If its `effective_to ≤ D`, nothing is in force;
  an older version does not revive. Retired, rejected, draft and pending versions are never evaluated.

### Endpoints

| Method and path | Permission | Notes |
|---|---|---|
| `GET /rules` | rules:read | Register: owner, version in force today, latest status, `can_manage`, `can_publish`, disclaimer |
| `GET /rules/catalog` | rules:read | Fields, types, and allowed operators with their value shapes |
| `POST /rules/validate` | rules:read | `{definition}` → `{valid, errors[{loc, msg}], summary}`. Writes nothing |
| `POST /rules` | rules:manage | Create a rule and draft v1 (`key`, `name`, `category`, `definition`, `effective_from`, …) |
| `GET /rules/{id}` | rules:read | Rule with versions (newest first, each with a readable `summary` and `in_force_today`) and test cases |
| `PATCH /rules/{id}` | rules:manage | Name, description, category, owner (the owner must hold rules:manage) |
| `POST /rules/{id}/versions` | rules:manage | New draft copied from `from_version_id` (default: latest) |
| `PATCH /rules/{id}/versions/{vid}` | rules:manage | Edit a draft |
| `POST /rules/{id}/versions/{vid}/submit` | rules:manage | Freeze for review |
| `POST /rules/{id}/versions/{vid}/approve`, `…/reject` | rules:publish | `{note}`; four-eyes |
| `POST /rules/{id}/versions/{vid}/retire` | rules:publish | `{reason}` |
| `GET /rules/{id}/compare?from=&to=` | rules:read | Both summaries and a structural diff `[{path, change, before, after}]` |
| `POST /rules/{id}/test-cases`, `DELETE …/test-cases/{case_id}` | rules:manage | Synthetic test cases |
| `POST /rules/{id}/versions/{vid}/test` | rules:read | Run the cases against a stored version. Writes nothing |
| `POST /rules/{id}/test-definition` | rules:manage | Run the cases against an unsaved definition. Writes nothing |
| `POST /rules/simulate` | rules:manage | What-if simulation (below) |
| `POST /applications/{id}/validation-runs` | validation:run and edit access | `{evaluation_date?}`; 409 `no_rules_in_force` |
| `GET /applications/{id}/validation-runs`, `…/{run_id}` | applications:read and access | Runs, newest first; one run with results and traces |
| `GET /applications/{id}/validation-runs/{run_id}/reproduction` | applications:read and access | Re-evaluates the stored snapshot. Read-only |

Applications follow the usual ownership policy: someone else's application answers 404.

Other error codes: `duplicate_rule_key`, `draft_exists`, `pending_exists`, `invalid_rule` (422, with `details`),
`invalid_test_case` (422), `invalid_owner`, `invalid_transition`, `no_changes`.

### Synthetic test cases

```json
{"synthetic": true, "evaluation_date": "2026-10-23",
 "application": {"application_type": "kyc"},
 "documents": [{"name": "Synthetic ID", "fields": {"date_of_birth": {"value": "2015-01-01", "status": "found", "quality": "high", "source": "extracted"}}}],
 "evidence": {"person_name": {"outcome": "pass", "quality": "high"}}, "evidence_stale": false}
```

Unknown field keys or evidence groups, extra properties, and cases without `"synthetic": true` are rejected with
422 `invalid_test_case`. Cases describe invented inputs only and are never built from application data.

### Validation runs (reproducible)

A run stores:

- the **exact rule version records**: id, number, content hash, full definition, effective window, source, owner
  and approver
- the **normalized input snapshot**: every document's field values with provenance, evidence outcomes with
  staleness, application attributes, and the evaluation date
- SHA-256 fingerprints of both, and the engine version

Runs and results are immutable. `…/reproduction` verifies both fingerprints and re-evaluates the stored snapshot
with the stored definitions, returning `{identical, snapshot_intact, differences, engine_version,
stored_engine_version}`. Publishing new versions later never changes stored runs.

### What-if simulation

`POST /rules/simulate` takes `{proposals: [{rule_id, version_id | definition}], application_ids?, evaluation_date?}`.
For each application you can see (by default, the 50 most recently updated), it evaluates the rules in force
(**before**) and the rules in force with each proposal substituted (**after**). Each row reports both outcomes,
`changed`, and the after-trace.

Evaluation happens in memory: no rule, version, test case, validation run or result is created or modified. The
only write is an audit event recording the simulation and how many applications it read.

### Audited events

`rule.created`, `rule.metadata_updated`, `rule.version_created`, `rule.draft_updated`, `rule.test_case_added`,
`rule.test_case_deleted`, `rule.submitted` (with the test summary), `rule.published` (content hash, effective
window, note), `rule.rejected`, `rule.retired`, `rule.simulated`, `validation.run` (run id, fingerprints, summary,
previous run, trigger).

## Review and Resolution Center (Phase 7)

### Review items

Every validation run syncs the queue (in the same transaction as the run):

| New result for a rule | Existing items for the application and rule | Effect |
|---|---|---|
| fail / review / insufficient | an active item | the item now points at the new result; a `revalidated` entry records before/after |
| fail / review / insufficient | latest item confirmed or dismissed on **identical evidence** (same outcome, reason and traced values) | the decision stands; a `revalidated` entry with `decision_stands: true`; no new item |
| fail / review / insufficient | none, or different evidence | a new item, `previous_item_id` linking the earlier one |
| pass / not_applicable | an active item | the item becomes `resolved` |

Categories: `failure` (fail), `uncertain` (review), `missing` (insufficient). Priority = severity (critical 40,
high 30, medium 20, low 10) + category (failure 30, uncertain 20, missing 10). At most one **active** item
(`open`, `awaiting_document`, `escalated`) exists per application and rule (partial unique index). Items are never
deleted, and the rule results they point to (`origin_result_id`, `current_result_id`) are immutable.

### Access

| Operation | Requirement |
|---|---|
| Read queue and items | `applications:read` and read access to the item's application (else 404) |
| Any action | `review:resolve` **and** edit access to the application (owner, contributor, or an oversight role), application not archived |
| Decide or return an **escalated** item | additionally `applications:read_all` (compliance manager or administrator) — 403 `oversight_required` |
| Dismiss a **critical failure** | additionally `applications:read_all` |
| Assignee | an active user who could act on the item (listed by `GET /reviews/{id}/assignees`) |

Reviewers have `review:resolve` but not `rules:manage` or `rules:publish`: they can't author, approve or simulate
rules.

### Endpoints

| Method and path | Notes |
|---|---|
| `GET /reviews?status=&category=&assignee=&severity=&application_id=&q=&limit=&offset=` | `status`: `active` (default), `closed`, `all` or one status; `assignee`: `me`, `unassigned` or a user id. Returns items with application, `total`, and `counts` (by status, by active category, `mine`) |
| `GET /reviews/{id}` | Item, current rule result and trace, run, rule version record (source, owner, approver, summary), uncertainty reasons, every current-run field the rule reads (original extraction, value at validation, current value, corrections, page box), relevant evidence findings, full history, earlier items, the rule's outcome across runs, and `permissions` |
| `GET /reviews/{id}/assignees` | `review:resolve` |
| `POST /reviews/{id}/actions` | `{action, expected_version, request_id?, reason?, assignee_id?, document_description?}` |
| `POST /reviews/{id}/corrections` | `{expected_version, request_id?, document_id, field_id, value, reason}` |

### Actions

| Action | From | To | Reason |
|---|---|---|---|
| `assigned` / `unassigned` | active | same | required (≥ 5) when taking an item from someone else |
| `commented` | any | same | the comment (required) |
| `escalated` | open, awaiting_document | escalated | required (≥ 5) |
| `document_requested` | open | awaiting_document | `document_description` required (≥ 5) |
| `resumed` | awaiting_document, escalated* | open | required (≥ 5) when returning an escalated item |
| `confirmed` | active* | confirmed | required (≥ 5) |
| `dismissed` | active* | dismissed | required (≥ 10) |
| `reopened` | confirmed, dismissed | open | required (≥ 5) |

\* escalated items need oversight. `opened`, `revalidated` and `field_corrected` are recorded by the system and
can't be submitted. Invalid transitions answer 409 `invalid_transition`; missing reasons 422
`invalid_review_action`.

### Concurrency and duplicates

- **Optimistic locking.** Every action names `expected_version`. A mismatch answers 409 `stale_item` with the
  current version, status and assignee in `details`. Every action, comments included, advances the version, so a
  decision is always made on the latest state. The version is also SQLAlchemy's `version_id_col`, so two writers
  racing between read and write can't both succeed.
- **Idempotency.** A `request_id` (8–64 characters `[A-Za-z0-9_-]`) is unique per item. Repeating it returns the
  original action with `replayed: true` instead of acting again, even if the version moved on. Reusing it for a
  different action answers 409 `request_id_reused`.

### Corrections and revalidation

`POST /reviews/{id}/corrections` appends a `FieldCorrection` through the extraction service (the extracted field is
never modified) and a `field_corrected` history entry with the original extraction, `before`, `after` and the rules
affected, in one transaction. A correction affects compliance when a rule in force on the item's evaluation date
reads the field directly or through an evidence group containing it. Then:

1. the current evidence analysis is refreshed if one exists, and
2. a new validation run is created for the same evaluation date with `trigger: "correction"`,
   `trigger_data: {review_item_id, correction_id, action_id}` and `previous_run_id` set, which syncs the queue.

The response's `revalidation` reports `performed`, the new `run_id`, `previous_run_id` and `summary`, or why it
didn't run (no affected rule; not allowed to run validation; no rules in force). The correction is kept either way.

### Run lineage

Validation runs now carry `previous_run_id` (the application's latest run when the run was created), `trigger`
(`manual` or `correction`) and `trigger_data`. `GET …/validation-runs/{run_id}` also returns `next_run_ids`.

### Immutable history and audit

`review_actions` rows are append-only: an ORM guard and database triggers (SQLite and PostgreSQL) block UPDATE and
DELETE. Each entry records the actor, time, from/to status, reason and structured data (before/after values,
assignees, run and result ids). Every action is also written to the hash-chained audit trail as `review.<action>`
(`review.assigned`, `review.commented`, `review.escalated`, `review.document_requested`, `review.resumed`,
`review.confirmed`, `review.dismissed`, `review.reopened`, `review.field_corrected`), plus
`extraction.field_corrected` for corrections.

## AI assistance (Phase 9)

AI is advisory. It can **suggest** a document type, **suggest** field values quoted from page text, and
**explain** a result VerifyFlow already computed. It never determines authenticity, changes rules or rule results,
authorizes anyone, or feeds anything into the rule engine, trust checks or review decisions. Every endpoint below
answers with a deterministic fallback when AI is disabled, unconfigured, over budget, rate limited or failing, so the
application is fully usable without an external AI service.

### Architecture

| Layer | Module | Responsibility |
|---|---|---|
| Provider interface | `app/integrations/ai/base.py` | `AIProvider` protocol (`status`, `generate`, `ping`), provider-neutral errors with stable codes |
| Providers | `disabled.py`, `anthropic_provider.py` | No-AI mode; Claude through the official `anthropic` SDK (structured outputs, no tools, SDK retries off) |
| Registry | `registry.py` | `VERIFYFLOW_AI_PROVIDER` → provider. Unknown names fail safe to disabled |
| Gateway | `gateway.py` | The only call path: input cap, rate limits, daily budget, timeout, bounded retries, output validation, health |
| Assist | `app/assist/` | Egress policy and data framing, strict output schemas, content guard, versioned prompts |
| Service | `app/services/ai_service.py`, `ai_context.py` | Access control, context built from stored records, reference validation against the database, persistence, audit |

### Endpoints

| Method | Path | Requires | Description |
|---|---|---|---|
| GET | `/ai/status` | `system:read` | Provider state and health, egress policy, limits, today's spend, task availability. Never includes credentials. |
| POST | `/ai/status/check` | `users:manage` | Reachability and credentials check (models lookup; spends no tokens). Audited as `ai.health_checked`. |
| GET | `/ai/explanations?subject_type=&subject_id=` | `documents:read` + application read access | Latest stored explanation (if any), the deterministic result and the deterministic explanation. |
| POST | `/ai/explanations` | `validation:run` + edit access, live application | `{subject_type: "review_item" \| "evidence_finding", subject_id, refresh}`. Identical input reuses the stored answer unless `refresh`. |
| GET | `/ai/applications/{app}/documents/{doc}` | `documents:read` + read access | Latest classification and field suggestions with provider state and fallback. |
| POST | `/ai/applications/{app}/documents/{doc}/classification` | `validation:run` + edit access | `{refresh}`. Needs egress policy `page_text`. |
| POST | `/ai/applications/{app}/documents/{doc}/field-suggestions` | `validation:run` + edit access | `{refresh}`. Needs egress policy `page_text`. |

Readers without request rights (auditors, viewer members) get stored results and the fallback with
`can_request: false`; their POSTs return 403. Other applications' subjects return 404.

### Response shape

`ExplanationOut`: `subject`, `deterministic` (the authoritative result: outcome, severity, reason, rule id, version
and source reference, or the finding's outcome and evidence quality), `fallback.statements` (template-built from the
same records), `ai` (an `InteractionOut` or `null`), `error` (`{code, message}` when the request was refused before
reaching the provider), `provider`, `can_request`, `limitations`.

`InteractionOut`: `interaction_id`, `status` (`succeeded`, `partial`, `rejected`, `failed`), `error`, `output`
(validated output only), `validation` (what was dropped and why), `provider`, `model`, `prompt_version`,
`created_at`, `created_by`, `cached`, `stale` (the records changed since), `egress` (the manifest below), `usage`
(`input_tokens`, `output_tokens`, `cost_usd`, `attempts`, `duration_ms`).

Each statement is `{text, references: [{id, kind, label, link}]}`. `link` is built by the server from the stored
record (`field` → inspector page and field, `rule_result` → application, `rule_version` → rule, `finding` → evidence
graph), never from model text.

### Data egress

`VERIFYFLOW_AI_DOCUMENT_EGRESS` is a ceiling checked per task:

| Policy | What may leave | Tasks available |
|---|---|---|
| `none` (default) | Rule and finding metadata: rule names, outcomes, reason codes, field labels, page numbers, quality. File names become "Document 1", values become "(withheld by policy)". | Explanations |
| `extracted_values` | + extracted and corrected values, file names, correction reasons, stored finding explanations. Identifier values are masked to the last 4 characters while `VERIFYFLOW_AI_MASK_IDENTIFIERS=true`. | Explanations |
| `page_text` | + page text from the current extraction, whole pages up to `VERIFYFLOW_AI_MAX_INPUT_CHARS` | Explanations, classification, field suggestions |

Every interaction stores a manifest: `policy`, `categories` sent, `withheld`, `documents`, `pages` (number and
character count), `masked_values`, `truncated`, `chars_sent`, and `injection_signals`. The prompt text itself is not
stored; its SHA-256 is part of `input_fingerprint`.

### Prompt injection

Document content is untrusted. The defences are structural, not heuristic:

- document text and stored values are sent inside `<untrusted_document_text>` / `<record>` elements that the system
  prompt declares to be data, never instructions; copies of those delimiters inside content are replaced with
  `[tag removed]`, and values are escaped, so a document can't close the element;
- the model is given **no tools**, and must answer in a fixed JSON schema (structured outputs, then re-validated with
  `extra="forbid"` Pydantic models);
- no secret is ever in the request (the API key is used only to construct the SDK client);
- every output is checked server-side (below), and nothing it returns can change application state other than the
  advisory `ai_interactions` row.

Heuristic signals (text that asks to ignore instructions, change role, reveal secrets, run tools or declare a verdict)
are recorded in the manifest and shown to the reviewer as a warning. They are informational only.

### Output validation

- **Explanations.** Every statement must cite at least one record id (`<kind>:<32 hex>`, kinds `rule_result`,
  `rule_version`, `field`, `correction`, `finding`, `evidence_ref`). Each cited id is checked against the database
  (the row exists and belongs to the same application; a rule version must have produced a result there) and against
  the set that was sent. Rejection reasons: `malformed`, `not_found`, `other_application`, `not_in_context`. A
  statement with any rejected citation is dropped. Statements and caveats that claim authenticity, an application
  decision, that a deterministic result is wrong or should be overridden, contain links, or mention credentials are
  dropped too. If nothing is left, the status is `rejected` and only the deterministic explanation is shown.
- **Classification.** The type must be one of a fixed list (`passport`, `national_id_card`, `driving_licence`,
  `residence_permit`, `birth_certificate`, `bank_statement`, `utility_bill`, `payslip`, `tax_document`,
  `company_registration`, `other`, `unknown`). Cited pages that weren't sent are dropped; a rationale that fails the
  content checks is removed. The suggestion is never applied to the document.
- **Field suggestions.** Each suggestion must name a configured field, cite a page that was sent, quote text that
  appears on that page (whitespace-insensitive), give a value that appears in the quote, and pass the field's own
  normalizer. It is compared with the current extracted or corrected value (`matches_extraction`,
  `differs_from_extraction`, `not_extracted`) and never written; a person uses the correction workflow.

### Failures, limits and cost

| Code | Meaning | Retried |
|---|---|---|
| `ai_unavailable` | Disabled, unknown provider or no API key | no (not attempted) |
| `ai_egress_blocked` / `ai_no_text` | The policy forbids the content the task needs / no extracted text | no (not attempted) |
| `ai_budget_exceeded` / `ai_input_too_large` | The estimated worst-case cost would exceed today's budget / input over the cap | no (not attempted) |
| `ai_local_rate_limit` / `ai_user_rate_limit` | Process-wide per-minute or per-user per-hour limit | no (not attempted) |
| `ai_timeout`, `ai_rate_limited`, `ai_unreachable`, `ai_provider_error` (5xx) | Transient provider failures | yes, up to `VERIFYFLOW_AI_MAX_RETRIES`, exponential backoff 0.5 s, 1 s, 2 s … (max 8 s) |
| `ai_auth_failed`, `ai_model_unavailable`, `ai_bad_request` | Configuration problems | no |
| `ai_refused` | The model declined (after the provider's server-side fallback, when enabled) | no |
| `ai_empty_output`, `ai_invalid_output`, `ai_truncated_output` | No content, not JSON, wrong shape, or cut off at the output limit | no |
| `ai_all_rejected` | The answer parsed, but nothing survived validation | — |

The budget is a UTC-day ceiling over `ai_interactions.cost_usd`, computed from the configured per-million-token
prices. Before each call the gateway estimates the worst case (input characters ÷ 3 as tokens, plus the full output
limit) and refuses the call if it could exceed the ceiling. Identical requests reuse the stored answer.

### Persistence and audit

`ai_interactions` (migration `0010_ai_interactions`) stores every request that reached a provider, successful or
not. It is append-only (ORM guard plus database triggers). Each row is mirrored in the audit chain as `ai.requested`
(task, subject, status, error code, model, token counts, cost, egress categories and size, number of injection
signals; never content). Requests refused before anything left the environment are audited as `ai.blocked`.

### Logging

The gateway logs task, model, token counts, cost, duration, attempts and error codes, never prompts or output. The
redaction filter also removes Anthropic-style keys (`sk-ant-…`) and `x-api-key` values from any log text, and
summarizes `prompt`, `document_text`, `page_text`, `model_output` and similar keys as their length. The `anthropic`,
`httpx`, `httpx2` and `httpcore` loggers are pinned to WARNING so request bodies are never logged at DEBUG.

## Governance and insights (Phase 10)

Every number on the Command Center and in Governance & Insights is a database aggregate over persisted records,
defined in `app/insights/definitions.py` and served by `GET /insights/definitions`. Nothing is estimated, sampled or
padded; an empty scope shows zeros and an empty state.

### Scope, time basis and de-duplication

- **Scope.** Aggregates cover only applications the requesting user can see (owner or member; every application for
  roles with `applications:read_all`). Optional filters: `application_type`, and `include_synthetic=false` to exclude
  synthetic demo applications. Rule governance events are global (rules aren't application-scoped).
- **Two time bases, never mixed.** `current` metrics describe records now and ignore the window. `window` metrics
  count events whose timestamp (named per metric) falls inside `from`–`to`: UTC dates, both inclusive, at most 366
  days, default the last 30 days. `from` after `to`, or a longer span, is a 422 `invalid_window`.
- **No double counting.** Current findings use only each application's latest validation run (by `created_at`,
  ties by id). Historical case counts and rule-version outcomes use the latest run per application *inside the
  window*. Run counts are explicitly run-level. Review items are one per application and rule however many runs
  produced them.
- **Separate categories.** Engine results (`fail`, `review`, `insufficient` from the latest run) are reported
  separately from human decisions (review items a person confirmed or dismissed).
- **False positives.** Per rule and category: of the items whose latest confirm / dismiss / reopen decision in the
  window is a confirm or dismiss, the share dismissed. Only users with `review:resolve` can record those decisions;
  items closed automatically by a later run, and items reopened after their last decision, are excluded.
- **Rates.** `null` when the denominator is zero, never 0 by assumption.

### Endpoints

All take `from`, `to` (UTC dates) and, except rule governance, `application_type` and `include_synthetic`.

| Method | Path | Requires | Returns |
|---|---|---|---|
| GET | `/insights/definitions` | `system:read` | Every metric: `key`, `label`, `group`, `basis` (`current` / `window`), `definition`, `source`, `time_field`, `dedup`, `unit` |
| GET | `/insights/overview` | `system:read` | `scope` (with `applications` and `synthetic_applications`), `current` (applications, documents, findings with rates, evidence, human decisions, review backlog, extraction quality), `window` (applications created per day, processing jobs, validation runs per day and trigger, cases evaluated, review decisions, corrections) |
| GET | `/insights/review` | `applications:read` | Backlog by status × category and by age, workload per assignee, false positives overall, by category and by rule |
| GET | `/insights/rules` | `rules:read` | Rule-version usage (runs, applications, latest outcomes) and the validation run history (`limit` ≤ 200, `offset`) |
| GET | `/insights/rule-governance` | `rules:read` | Rule-version lifecycle events (created, submitted, approved, rejected, retired) with actor, detail, content hash and the four-eyes check; `rule_id`, `limit`, `offset` |
| GET | `/exports/datasets` | `system:read` | The export datasets and whether this user may export each |
| POST | `/exports` | `exports:create` (+ dataset rules below) | The file (`Content-Disposition: attachment`), with `X-Export-Rows`, `X-Export-Truncated`, `X-Export-Audit-Seq` |

### Exports

`POST /exports` body: `{dataset, format: "csv"|"json", date_from, date_to, application_type, include_synthetic,
include_document_values, reason, action, entity_type}`.

| Dataset | Needs | Document content |
|---|---|---|
| `metrics_summary` | `exports:create` | No: every aggregate, flattened (CSV) or with the overview and definitions (JSON) |
| `review_items` | `exports:create` | No: rule, category, outcome, severity, status, assignee, decision metadata |
| `validation_results` | `exports:create` | No: latest run per application in the window; outcomes and reasons, no values or traces |
| `rule_history` | `exports:create` | No |
| `audit_events` | `exports:create` + `audit:read` | No; event `data` (which can hold before/after values) only as a sensitive export |
| `extracted_fields` | `exports:sensitive` | Yes: current extracted, normalized and corrected values |

A sensitive export also needs `include_document_values: true` and a `reason` of at least 10 characters. Raw page
text and stored files are never exportable. Exports are capped at 50,000 rows (`X-Export-Truncated: true` when cut).
CSV is UTF-8 with BOM, and cells beginning with `=`, `+`, `-`, `@`, tab or carriage return are prefixed with `'` so
spreadsheets don't execute them. Rows of synthetic applications carry `synthetic: true`.

Every export is recorded as `export.created` (dataset, format, scope, filters, row count, truncation, whether it
contains document values, the reason, byte size and the SHA-256 of the file). Refusals inside the endpoint are
recorded as `export.denied` with outcome `failure`; requests without `exports:create` are refused by the permission
check and recorded as `security.permission_denied`. Both are ordinary, append-only audit events.

### Synthetic demo data

`python -m app.cli seed-demo --owner-email you@example.org` (refused in production) creates three applications titled
`[SYNTHETIC DEMO] …` with `is_synthetic = true` (migration `0011_synthetic_flag`) and fictional documents, and runs
them through the real pipeline: extraction, evidence analysis, and validation if published rules are in force. Rules
are never seeded. Synthetic applications are labelled in lists, on their page and in exports, and the insights state
how many are included and can exclude them. The command is audited as `demo.seeded`.
