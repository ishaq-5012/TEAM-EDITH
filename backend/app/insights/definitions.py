"""The metric catalog: every number on the Command Center and in Governance & Insights is defined here.

Each metric states what it counts, its data source (tables), its time basis and how double counting is avoided.
Two time bases exist and are never mixed:

- ``current``: the state of the records *now*. The date window does not apply.
- ``window``: events whose timestamp (named in ``time_field``) falls in the selected window. Windows are UTC dates;
  ``from`` is inclusive and ``to`` is inclusive (the whole day).

All metrics are scoped to the applications the requesting user may see (owner, member, or a role that reads all
applications), optionally narrowed by application type and by whether synthetic demo applications are included.
No metric is estimated, sampled or padded: every value is a database aggregate over persisted records.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

LATEST_RUN = (
    "Only each application's latest validation run counts (by created_at, ties broken by id), so repeated runs "
    "of the same application never count the same rule twice."
)
LATEST_RUN_IN_WINDOW = (
    "Per application, only the latest validation run created inside the window counts, so re-running "
    "validation does not inflate case counts."
)


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    group: str
    basis: str  # "current" | "window"
    definition: str
    source: str
    time_field: str | None = None
    dedup: str = ""
    unit: str = "count"

    def as_dict(self) -> dict:
        return asdict(self)


METRICS: list[Metric] = [
    # ---------------------------------------------------------------- applications and processing
    Metric("applications.by_status", "Applications by status", "applications", "current",
           "Applications in scope, grouped by their current lifecycle status.", "applications.status"),
    Metric("applications.synthetic", "Synthetic demo applications", "applications", "current",
           "Applications in scope created by the development-only seed-demo command (is_synthetic = true).",
           "applications.is_synthetic"),
    Metric("applications.created", "Applications created", "applications", "window",
           "Applications in scope created in the window, per UTC day.", "applications.created_at",
           "applications.created_at"),
    Metric("documents.by_status", "Documents by processing status", "applications", "current",
           "Documents of applications in scope, grouped by current processing status.", "documents.status"),
    Metric("processing.jobs", "Processing jobs finished", "applications", "window",
           "Intake/extraction jobs that finished in the window, by outcome (succeeded or failed). Every attempt "
           "is a separate job, so retries are counted as attempts.", "processing_jobs.status",
           "processing_jobs.finished_at"),
    # ---------------------------------------------------------------- findings
    Metric("findings.current", "Rule findings by outcome and severity", "findings", "current",
           "Rule results of each application's latest validation run, by outcome and the rule's severity. "
           "not_applicable results are listed but excluded from rates.", "rule_results, validation_runs",
           dedup=LATEST_RUN),
    Metric("findings.engine_failures", "Rule failures (engine)", "findings", "current",
           "Latest-run rule results with outcome 'fail': the rule engine found the configured condition violated. "
           "Not a human decision and not a legal determination.", "rule_results.outcome", dedup=LATEST_RUN),
    Metric("findings.review_required", "Review required (engine)", "findings", "current",
           "Latest-run rule results with outcome 'review': low-confidence inputs, or rules that route violations "
           "to people instead of failing.", "rule_results.outcome", dedup=LATEST_RUN),
    Metric("findings.insufficient", "Insufficient evidence", "findings", "current",
           "Latest-run rule results with outcome 'insufficient': data the rule needs was missing or unusable.",
           "rule_results.outcome", dedup=LATEST_RUN),
    Metric("rates.uncertainty", "Uncertainty rate", "findings", "current",
           "review ÷ (pass + fail + review + insufficient) over latest-run rule results.", "rule_results.outcome",
           dedup=LATEST_RUN, unit="ratio"),
    Metric("rates.insufficient", "Insufficient-evidence rate", "findings", "current",
           "insufficient ÷ (pass + fail + review + insufficient) over latest-run rule results.",
           "rule_results.outcome", dedup=LATEST_RUN, unit="ratio"),
    Metric("evidence.current", "Cross-document findings", "findings", "current",
           "Findings of each application's current evidence analysis, by outcome and severity. Exactly one analysis "
           "per application is current.", "evidence_findings, evidence_analyses.is_current"),
    Metric("review.human_confirmed", "Confirmed failures (human)", "findings", "current",
           "Review items a person confirmed (the finding stands). Separate from engine failures.",
           "review_items.status = confirmed"),
    Metric("review.human_dismissed", "Dismissed findings (human)", "findings", "current",
           "Review items a person dismissed with a recorded reason (the finding does not stand).",
           "review_items.status = dismissed"),
    # ---------------------------------------------------------------- validation history
    Metric("validation.runs", "Validation runs", "validation", "window",
           "Validation runs created in the window, per UTC day and trigger (manual or correction). Run-level: "
           "an application validated three times counts three runs.", "validation_runs",
           "validation_runs.created_at"),
    Metric("validation.cases", "Cases evaluated", "validation", "window",
           "Rule results, by outcome, from the latest run per application inside the window.",
           "rule_results, validation_runs", "validation_runs.created_at", dedup=LATEST_RUN_IN_WINDOW),
    Metric("rules.version_usage", "Rule-version usage", "validation", "window",
           "Per rule version: validation runs in the window that evaluated it, distinct applications, and the "
           "outcomes of its results in each application's latest run in the window.",
           "rule_results, validation_runs, rule_versions", "validation_runs.created_at",
           dedup=LATEST_RUN_IN_WINDOW),
    Metric("rules.governance", "Rule governance events", "validation", "window",
           "Rule-version lifecycle events (created, submitted, approved, rejected, retired) in the window, read "
           "from the rule_versions record itself, with the four-eyes check (approver differs from author and "
           "submitter).", "rule_versions", "the event's own timestamp"),
    # ---------------------------------------------------------------- review
    Metric("review.backlog", "Review backlog", "review", "current",
           "Active review items (open, awaiting document, escalated) by status, category and severity.",
           "review_items.status"),
    Metric("review.unassigned", "Unassigned active items", "review", "current",
           "Active review items with no assignee.", "review_items.assignee_id"),
    Metric("review.workload", "Workload by assignee", "review", "current",
           "Active review items per assignee.", "review_items.assignee_id"),
    Metric("review.age", "Backlog age", "review", "current",
           "Active review items by age since the item was opened: under 1 day, 1–7 days, 7–30 days, over 30 days.",
           "review_items.created_at"),
    Metric("review.opened", "Review items opened", "review", "window",
           "Review items opened in the window.", "review_items.created_at", "review_items.created_at"),
    Metric("review.decisions", "Reviewer decisions", "review", "window",
           "Confirm and dismiss decisions recorded in the window (each decision action counts once).",
           "review_actions.action", "review_actions.created_at"),
    Metric("review.false_positive_rate", "False-positive rate", "review", "window",
           "Per rule and category: of the items whose latest confirm/dismiss/reopen decision in the window is a "
           "confirm or dismiss, the share dismissed. Only people with review:resolve can record these decisions; "
           "items resolved automatically by a later run, and items reopened after their last decision, are "
           "excluded.", "review_actions, review_items", "review_actions.created_at", unit="ratio"),
    # ---------------------------------------------------------------- extraction quality
    Metric("extraction.fields", "Extracted fields by status", "extraction", "current",
           "Fields of each document's current extraction run, by status (found, ambiguous, invalid, missing).",
           "extracted_fields, extraction_runs.is_current"),
    Metric("extraction.pages", "Pages by text source and OCR status", "extraction", "current",
           "Pages of current extraction runs by where their text came from and OCR outcome.",
           "document_pages, extraction_runs.is_current"),
    Metric("extraction.correction_rate", "Correction rate", "extraction", "current",
           "Current-run fields that have at least one human correction ÷ current-run fields with a value "
           "(found or ambiguous) plus corrected fields.", "field_corrections, extracted_fields", unit="ratio"),
    Metric("extraction.corrections", "Corrections made", "extraction", "window",
           "Human field corrections recorded in the window.", "field_corrections.created_at",
           "field_corrections.created_at"),
]

BY_KEY = {m.key: m for m in METRICS}

ACTIVE_REVIEW = ("open", "awaiting_document", "escalated")
DECISIONS = ("confirmed", "dismissed", "reopened")
