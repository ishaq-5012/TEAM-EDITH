# VerifyFlow productization audit

Reviewed 2026-10-25. This inventory describes the code that existed before the integration and five-role work began. It is not a claim of regulatory certification. The portal and VerifyFlow are separate applications and databases.

## Feature preservation and repair matrix

| Feature | Existing implementation and persistence | Baseline status | Required repair or integration |
|---|---|---|---|
| Command Center | `backend/app/services/insights_service.py`, `app/insights/definitions.py`, `frontend/src/features/command-center/`; SQL aggregates | Uses persisted VerifyFlow records; covered by `test_insights.py` | Include intake-delivery failures and portal submissions after integration; keep role and tenant filters |
| Application Workspace | `backend/app/api/routes/applications.py`, `app/models/application.py`, `frontend/src/features/applications/` | CRUD, membership, private document storage, processing and history work for VerifyFlow-owned applications | Map portal application ID, submission version and fields to persisted VerifyFlow records; preserve current APIs |
| Portal institution workflow | `mock-aicte-portal/app/web.py`, `services.py`, `db.py`, `catalog.py` | Registration, form, versioned uploads, submit, clarification, resubmit and status history are persisted | Add durable outbox and authenticated delivery; do not mark receipt before acknowledgement |
| Document extraction | `backend/app/extraction/`, extraction service, inspector UI | PDF text and OCR fallback with source pages/coordinates; tests exist | Preserve source version when portal sends a replacement; show processing errors explicitly |
| Evidence Intelligence Graph | `backend/app/evidence/`, `models/evidence.py`, `frontend/src/features/evidence/` | Analyses/findings are persisted and have graph/list/network views; tests exist | Tie imported submissions and document versions to the graph; check retry idempotency and no dangling links |
| Compliance Studio | `backend/app/rules/`, `models/rules.py`, rule service/API, frontend compliance pages | Typed JSON rules, immutable submitted content, test cases, what-if and four-eyes check exist | Separate author from the dedicated second approver role; add explicit source-verification status and AICTE category mapping |
| Review and Resolution | `backend/app/services/review_service.py`, review routes and UI | Persisted queue, assignments, corrections, actions and history; tests exist | Restrict reviewer scope to assignment; add configurable routing and portal clarification/status sync |
| Trust and Authentication | `backend/app/trust/`, trust service/API and UI | Hash, signature, trust-anchor, revocation and registry checks with stored runs | Keep authority claims conditional on configured trustworthy mechanisms; link imported document hashes |
| Governance and Insights | Audit service/API, export service and governance UI | VerifyFlow audit is append-only and hash chained; exports are audited | Portal audit is currently a plain table; add delivery and status audit, keep auditor read-only |
| Officer accounts | `backend/app/core/roles.py`, user service/routes and frontend role labels | Four backend roles, one role per user, institution tenant isolation | Add distinct Second Approver; remove rule-publish authority from administrator and Compliance Manager; exercise all forbidden paths |
| Integration | No portal-to-VerifyFlow transport currently. VerifyFlow has no portal intake endpoint. | **Absent** | Authenticated, idempotent intake; durable retry; document and submission version mapping; bidirectional status and clarification reconciliation |

## Existing hardcoded configuration and migration disposition

| Location | Current content | Disposition |
|---|---|---|
| `mock-aicte-portal/app/catalog.py` | 12 demo categories, field flags, document codes and requirements | Keep as explicitly demo UI configuration; map to a versioned intake contract. Do not mislabel as official AICTE requirements |
| `backend/app/core/roles.py` | Four roles and their permissions; admin receives every permission | Replace with five explicit permission sets and server-side negative tests |
| `backend/app/extraction/field_definitions.json` | Extraction aliases and types | Preserve as versioned extraction configuration; track configuration version in run metadata |
| `backend/app/evidence/comparison_config.json` | Comparison groups, field mapping and priority labels | Preserve and version; regression-test comparisons against synthetic portal documents |
| `backend/app/evidence/priority.py`, `review_service.py` | Priority weights | Keep as documented prototype policy, separate from legal compliance outcomes |
| `backend/app/rules/schema.py`, `engine.py` | Allowed operators, field catalogue and evaluator code | Preserve typed allowlist in code; keep rule definitions and applicability in governed database versions |
| `backend/app/trust/synthetic_registry.json` | Synthetic trust fixture | Development/test only; never claim real issuer verification |
| `backend/app/insights/definitions.py` | Metric definitions | Preserve code definitions with sources and time basis; add integration health metrics from persisted rows |
| `frontend/src/components/layout/modules.ts`, `src/features/**/statusMeta.ts` | Presentation labels, routes and status colors | Keep as UI metadata; derive permissions and business state from backend responses |
| `backend/app/services/demo_seed.py` and portal `manage.py seed` | Synthetic examples | Keep optional development seed paths isolated from live accounts and uploads |

## Source status

The [AICTE Approval Process Handbook 2024–2027](https://aicte-qa.aicte-india.org/sites/default/files/APH%20Final.pdf) supports the broad application categories used by the synthetic factory. Existing VerifyFlow rules are generic or internal demonstration policies; they are **not** a verified official AICTE rule catalogue. Later amendments and cycle-specific applicability need verification before any rule can be described as officially mandated. The synthetic factory catalogue in `mock-aicte-portal/synthetic_factory/catalogue.py` records two official-linked resolution references and labels other generated document requirements demo-only.

## Data preservation constraints

`backend/var/verifyflow.db` and `mock-aicte-portal/var/portal.sqlite3` contain working local data. Migrations must preserve both. Document storage is private in each app. The synthetic factory output in `mock-aicte-portal/synthetic_data/` is separate and is not automatically uploaded to either database.
