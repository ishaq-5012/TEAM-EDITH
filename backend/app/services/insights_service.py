"""Governance and insights aggregates over persisted records. Definitions: ``app.insights.definitions``.

Rules that hold for every function here:
- Scope first: only applications the user may see (``application_service.visible_filter``), optionally narrowed by
  application type and by excluding synthetic demo applications.
- Current-state numbers ignore the date window; window numbers filter on the timestamp their definition names.
- Findings count only each application's latest validation run (or the latest inside the window for historical
  case counts), so repeated runs never double count.
- Counts are SQL aggregates. Python only buckets already-filtered rows by UTC day and picks each review item's latest
  decision, both of which are exact.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import Select, and_, distinct, func, select
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.insights.definitions import ACTIVE_REVIEW, DECISIONS, METRICS
from app.models.application import Application, Document, ProcessingJob
from app.models.evidence import EvidenceAnalysis, EvidenceFinding
from app.models.extraction import DocumentPage, ExtractedField, ExtractionRun, FieldCorrection
from app.models.review import ReviewAction, ReviewItem
from app.models.rules import Rule, RuleResult, RuleVersion, ValidationRun
from app.models.user import User
from app.services import application_service

MAX_WINDOW_DAYS = 366
DEFAULT_WINDOW_DAYS = 30
RATE_OUTCOMES = ("pass", "fail", "review", "insufficient")


class InvalidWindow(DomainError):
    status_code = 422
    code = "invalid_window"


@dataclass(frozen=True)
class Scope:
    user: User
    date_from: date
    date_to: date  # inclusive
    application_type: str | None = None
    include_synthetic: bool = True

    @property
    def start(self) -> datetime:
        return datetime.combine(self.date_from, time.min, tzinfo=UTC)

    @property
    def end(self) -> datetime:  # exclusive
        return datetime.combine(self.date_to + timedelta(days=1), time.min, tzinfo=UTC)

    def describe(self) -> dict:
        return {
            "date_from": self.date_from.isoformat(),
            "date_to": self.date_to.isoformat(),
            "application_type": self.application_type,
            "include_synthetic": self.include_synthetic,
            "timezone": "UTC",
        }


def make_scope(
    user: User,
    date_from: date | None,
    date_to: date | None,
    application_type: str | None = None,
    include_synthetic: bool = True,
) -> Scope:
    today = datetime.now(UTC).date()
    date_to = date_to or today
    date_from = date_from or (date_to - timedelta(days=DEFAULT_WINDOW_DAYS - 1))
    if date_from > date_to:
        raise InvalidWindow("The window's start date is after its end date")
    if (date_to - date_from).days + 1 > MAX_WINDOW_DAYS:
        raise InvalidWindow(f"The window can span at most {MAX_WINDOW_DAYS} days")
    return Scope(user, date_from, date_to, (application_type or "").strip() or None, include_synthetic)


def definitions() -> list[dict]:
    return [m.as_dict() for m in METRICS]


# ------------------------------------------------------------------ building blocks


def app_ids(scope: Scope) -> Select:
    """Ids of the applications in scope."""
    stmt = select(Application.id)
    visible = application_service.visible_filter(scope.user)
    if visible is not None:
        stmt = stmt.where(visible)
    if scope.application_type:
        stmt = stmt.where(Application.application_type == scope.application_type)
    if not scope.include_synthetic:
        stmt = stmt.where(Application.is_synthetic.is_(False))
    return stmt


def _in_window(column, scope: Scope):  # noqa: ANN001, ANN202
    return and_(column >= scope.start, column < scope.end)


def latest_run_ids(scope: Scope, *, in_window: bool) -> Select:
    """Each in-scope application's latest validation run (optionally the latest created inside the window)."""
    rn = func.row_number().over(
        partition_by=ValidationRun.application_id,
        order_by=(ValidationRun.created_at.desc(), ValidationRun.id.desc()),
    ).label("rn")
    inner = select(ValidationRun.id.label("run_id"), rn).where(ValidationRun.application_id.in_(app_ids(scope)))
    if in_window:
        inner = inner.where(_in_window(ValidationRun.created_at, scope))
    sub = inner.subquery()
    return select(sub.c.run_id).where(sub.c.rn == 1)


def _counts(db: Session, stmt: Select) -> dict[str, int]:
    return {str(k): int(v) for k, v in db.execute(stmt).all()}


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _days(scope: Scope) -> list[str]:
    n = (scope.date_to - scope.date_from).days + 1
    return [(scope.date_from + timedelta(days=i)).isoformat() for i in range(n)]


def _day(dt: datetime) -> str:
    return dt.astimezone(UTC).date().isoformat()


def _outcome_severity(db: Session, run_ids: Select) -> tuple[dict[str, int], list[dict]]:
    rows = db.execute(
        select(RuleResult.outcome, RuleResult.severity, func.count())
        .where(RuleResult.run_id.in_(run_ids))
        .group_by(RuleResult.outcome, RuleResult.severity)
    ).all()
    by_outcome: Counter[str] = Counter()
    matrix = []
    for outcome, severity, n in rows:
        by_outcome[outcome] += n
        matrix.append({"outcome": outcome, "severity": severity, "count": int(n)})
    return dict(by_outcome), sorted(matrix, key=lambda r: (r["outcome"], r["severity"]))


# ------------------------------------------------------------------ overview


def overview(db: Session, scope: Scope) -> dict:
    apps = app_ids(scope)
    in_scope = db.execute(select(func.count()).select_from(apps.subquery())).scalar_one()
    synthetic = db.execute(
        select(func.count()).select_from(Application)
        .where(Application.id.in_(apps), Application.is_synthetic.is_(True))
    ).scalar_one()

    # Applications
    by_status = _counts(db, select(Application.status, func.count()).where(Application.id.in_(apps))
                        .group_by(Application.status))
    created = Counter(_day(c) for (c,) in db.execute(
        select(Application.created_at).where(Application.id.in_(apps), _in_window(Application.created_at, scope))
    ).all())

    # Documents and processing
    docs_in_scope = select(Document.id).where(Document.application_id.in_(apps))
    doc_status = _counts(db, select(Document.status, func.count()).where(Document.application_id.in_(apps))
                         .group_by(Document.status))
    jobs = _counts(db, select(ProcessingJob.status, func.count()).where(
        ProcessingJob.document_id.in_(docs_in_scope), ProcessingJob.finished_at.is_not(None),
        _in_window(ProcessingJob.finished_at, scope),
    ).group_by(ProcessingJob.status))
    finished = jobs.get("succeeded", 0) + jobs.get("failed", 0)

    # Findings: latest run per application
    latest = latest_run_ids(scope, in_window=False)
    apps_with_run = db.execute(select(func.count()).select_from(latest.subquery())).scalar_one()
    by_outcome, matrix = _outcome_severity(db, latest)
    rated = sum(by_outcome.get(o, 0) for o in RATE_OUTCOMES)

    # Evidence: the current analysis per application
    current_analyses = select(EvidenceAnalysis.id).where(
        EvidenceAnalysis.application_id.in_(apps), EvidenceAnalysis.is_current.is_(True)
    )
    ev_rows = db.execute(
        select(EvidenceFinding.outcome, EvidenceFinding.severity, func.count())
        .where(EvidenceFinding.analysis_id.in_(current_analyses))
        .group_by(EvidenceFinding.outcome, EvidenceFinding.severity)
    ).all()
    ev_by_outcome: Counter[str] = Counter()
    for o, _s, n in ev_rows:
        ev_by_outcome[o] += n

    # Review (current) and human decisions
    review_status = _counts(db, select(ReviewItem.status, func.count()).where(ReviewItem.application_id.in_(apps))
                            .group_by(ReviewItem.status))
    active = ReviewItem.status.in_(ACTIVE_REVIEW)
    backlog_category = _counts(db, select(ReviewItem.category, func.count()).where(
        ReviewItem.application_id.in_(apps), active).group_by(ReviewItem.category))
    backlog_severity = _counts(db, select(ReviewItem.severity, func.count()).where(
        ReviewItem.application_id.in_(apps), active).group_by(ReviewItem.severity))
    unassigned = db.execute(select(func.count()).select_from(ReviewItem).where(
        ReviewItem.application_id.in_(apps), active, ReviewItem.assignee_id.is_(None))).scalar_one()
    opened = db.execute(select(func.count()).select_from(ReviewItem).where(
        ReviewItem.application_id.in_(apps), _in_window(ReviewItem.created_at, scope))).scalar_one()
    decisions = _counts(db, select(ReviewAction.action, func.count()).where(
        ReviewAction.application_id.in_(apps), ReviewAction.action.in_(("confirmed", "dismissed")),
        _in_window(ReviewAction.created_at, scope)).group_by(ReviewAction.action))

    # Validation history
    runs = db.execute(select(ValidationRun.created_at, ValidationRun.trigger).where(
        ValidationRun.application_id.in_(apps), _in_window(ValidationRun.created_at, scope))).all()
    run_days: dict[str, Counter] = defaultdict(Counter)
    for created_at, trigger in runs:
        run_days[_day(created_at)][trigger] += 1
    window_latest = latest_run_ids(scope, in_window=True)
    cases_apps = db.execute(select(func.count()).select_from(window_latest.subquery())).scalar_one()
    cases_by_outcome, _ = _outcome_severity(db, window_latest)

    # Extraction quality: current runs only
    current_runs = select(ExtractionRun.id).where(
        ExtractionRun.document_id.in_(docs_in_scope), ExtractionRun.is_current.is_(True)
    )
    docs_with_run = db.execute(select(func.count()).select_from(current_runs.subquery())).scalar_one()
    field_status = _counts(db, select(ExtractedField.status, func.count()).where(
        ExtractedField.run_id.in_(current_runs)).group_by(ExtractedField.status))
    text_source = _counts(db, select(DocumentPage.text_source, func.count()).where(
        DocumentPage.run_id.in_(current_runs)).group_by(DocumentPage.text_source))
    ocr_status = _counts(db, select(DocumentPage.ocr_status, func.count()).where(
        DocumentPage.run_id.in_(current_runs)).group_by(DocumentPage.ocr_status))
    corrected_keys = select(FieldCorrection.document_id, FieldCorrection.field_key).distinct().subquery()
    corrected = db.execute(
        select(func.count()).select_from(ExtractedField).join(
            corrected_keys,
            and_(corrected_keys.c.document_id == ExtractedField.document_id,
                 corrected_keys.c.field_key == ExtractedField.field_key),
        ).where(ExtractedField.run_id.in_(current_runs))
    ).scalar_one()
    with_value = field_status.get("found", 0) + field_status.get("ambiguous", 0)
    corrected_without_value = db.execute(
        select(func.count()).select_from(ExtractedField).join(
            corrected_keys,
            and_(corrected_keys.c.document_id == ExtractedField.document_id,
                 corrected_keys.c.field_key == ExtractedField.field_key),
        ).where(ExtractedField.run_id.in_(current_runs), ExtractedField.status.not_in(("found", "ambiguous")))
    ).scalar_one()
    eligible = with_value + corrected_without_value
    corrections_window = db.execute(select(func.count()).select_from(FieldCorrection).where(
        FieldCorrection.document_id.in_(docs_in_scope), _in_window(FieldCorrection.created_at, scope))).scalar_one()

    return {
        "scope": {**scope.describe(), "applications": in_scope, "synthetic_applications": synthetic},
        "generated_at": datetime.now(UTC).isoformat(),
        "current": {
            "applications": {"total": in_scope, "by_status": by_status, "synthetic": synthetic},
            "documents": {"total": sum(doc_status.values()), "by_status": doc_status},
            "findings": {
                "applications_with_run": apps_with_run,
                "applications_without_run": in_scope - apps_with_run,
                "by_outcome": by_outcome,
                "by_outcome_severity": matrix,
                "engine_failures": by_outcome.get("fail", 0),
                "review_required": by_outcome.get("review", 0),
                "insufficient": by_outcome.get("insufficient", 0),
                "not_applicable": by_outcome.get("not_applicable", 0),
                "rates": {
                    "denominator": rated,
                    "uncertainty": _rate(by_outcome.get("review", 0), rated),
                    "insufficient": _rate(by_outcome.get("insufficient", 0), rated),
                },
            },
            "evidence": {
                "by_outcome": dict(ev_by_outcome),
                "by_outcome_severity": sorted(
                    [{"outcome": o, "severity": s, "count": int(n)} for o, s, n in ev_rows],
                    key=lambda r: (r["outcome"], r["severity"]),
                ),
            },
            "human": {"confirmed": review_status.get("confirmed", 0), "dismissed": review_status.get("dismissed", 0)},
            "review": {
                "backlog": sum(review_status.get(s, 0) for s in ACTIVE_REVIEW),
                "by_status": review_status,
                "backlog_by_category": backlog_category,
                "backlog_by_severity": backlog_severity,
                "unassigned": unassigned,
            },
            "extraction": {
                "documents_with_current_run": docs_with_run,
                "fields_by_status": field_status,
                "pages_by_text_source": text_source,
                "pages_by_ocr_status": ocr_status,
                "correction_rate": {"corrected": corrected, "eligible": eligible, "rate": _rate(corrected, eligible)},
            },
        },
        "window": {
            "applications_created": {
                "total": sum(created.values()),
                "by_day": [{"date": d, "count": created.get(d, 0)} for d in _days(scope)],
            },
            "processing": {
                "finished": finished,
                "by_status": jobs,
                "failure_rate": _rate(jobs.get("failed", 0), finished),
            },
            "validation": {
                "runs": len(runs),
                "by_trigger": dict(Counter(t for _, t in runs)),
                "by_day": [{"date": d, **{t: run_days[d].get(t, 0) for t in ("manual", "correction")}}
                           for d in _days(scope)],
                "cases": {"applications": cases_apps, "by_outcome": cases_by_outcome},
            },
            "review": {
                "opened": opened,
                "confirmed": decisions.get("confirmed", 0),
                "dismissed": decisions.get("dismissed", 0),
            },
            "extraction": {"corrections": corrections_window},
        },
    }


# ------------------------------------------------------------------ review backlog, workload, false positives


AGE_BUCKETS = (("under_1_day", 1), ("1_to_7_days", 7), ("7_to_30_days", 30), ("over_30_days", None))


def review(db: Session, scope: Scope) -> dict:
    apps = app_ids(scope)
    now = datetime.now(UTC)
    active_rows = db.execute(
        select(ReviewItem.status, ReviewItem.category, ReviewItem.severity, ReviewItem.assignee_id,
               ReviewItem.created_at)
        .where(ReviewItem.application_id.in_(apps), ReviewItem.status.in_(ACTIVE_REVIEW))
    ).all()
    matrix: Counter[tuple[str, str]] = Counter()
    ages: Counter[str] = Counter()
    per_user: dict[str | None, Counter] = defaultdict(Counter)
    for status, category, severity, assignee, created_at in active_rows:
        matrix[(status, category)] += 1
        days = (now - created_at).total_seconds() / 86400
        for name, limit in AGE_BUCKETS:
            if limit is None or days < limit:
                ages[name] += 1
                break
        per_user[assignee][severity] += 1
    users = {u.id: u for u in db.execute(select(User).where(User.id.in_([k for k in per_user if k]))).scalars()}
    workload = sorted(
        (
            {
                "user_id": uid,
                "full_name": users[uid].full_name if uid in users else None,
                "email": users[uid].email if uid in users else None,
                "count": sum(c.values()),
                "by_severity": dict(c),
            }
            for uid, c in per_user.items()
        ),
        key=lambda r: (r["user_id"] is None, -r["count"], r["full_name"] or ""),
    )

    # False positives: each item's latest decision in the window.
    actions = db.execute(
        select(ReviewAction.item_id, ReviewAction.action, ReviewAction.sequence)
        .where(ReviewAction.application_id.in_(apps), ReviewAction.action.in_(DECISIONS),
               _in_window(ReviewAction.created_at, scope))
        .order_by(ReviewAction.item_id, ReviewAction.sequence)
    ).all()
    last: dict[str, str] = {}
    for item_id, action, _seq in actions:
        last[item_id] = action
    decided = {i: a for i, a in last.items() if a in ("confirmed", "dismissed")}
    items = {
        i.id: i for i in db.execute(select(ReviewItem).where(ReviewItem.id.in_(list(decided)))).scalars()
    } if decided else {}
    by_rule: dict[str, dict] = {}
    by_category: dict[str, Counter] = defaultdict(Counter)
    for item_id, action in decided.items():
        it = items[item_id]
        row = by_rule.setdefault(it.rule_id, {"rule_id": it.rule_id, "rule_key": it.rule_key,
                                              "rule_name": it.rule_name, "confirmed": 0, "dismissed": 0})
        row[action] += 1
        by_category[it.category][action] += 1
    rules = sorted(
        ({**r, "decisions": r["confirmed"] + r["dismissed"],
          "false_positive_rate": _rate(r["dismissed"], r["confirmed"] + r["dismissed"])} for r in by_rule.values()),
        key=lambda r: (-(r["false_positive_rate"] or 0), -r["decisions"], r["rule_key"]),
    )
    confirmed = sum(1 for a in decided.values() if a == "confirmed")
    dismissed = len(decided) - confirmed
    return {
        "scope": scope.describe(),
        "backlog": {
            "total": len(active_rows),
            "by_status_category": [{"status": s, "category": c, "count": n} for (s, c), n in sorted(matrix.items())],
            "by_age": {name: ages.get(name, 0) for name, _ in AGE_BUCKETS},
            "unassigned": sum(per_user.get(None, Counter()).values()),
        },
        "workload": workload,
        "false_positives": {
            "decided_items": len(decided),
            "confirmed": confirmed,
            "dismissed": dismissed,
            "rate": _rate(dismissed, len(decided)),
            "reopened_excluded": sum(1 for a in last.values() if a == "reopened"),
            "by_category": {c: {"confirmed": n.get("confirmed", 0), "dismissed": n.get("dismissed", 0),
                                "false_positive_rate": _rate(n.get("dismissed", 0), sum(n.values()))}
                            for c, n in sorted(by_category.items())},
            "by_rule": rules,
        },
    }


# ------------------------------------------------------------------ rules: usage and validation history


def rules(db: Session, scope: Scope, *, limit: int, offset: int) -> dict:
    apps = app_ids(scope)
    window_runs = select(ValidationRun.id).where(
        ValidationRun.application_id.in_(apps), _in_window(ValidationRun.created_at, scope)
    )
    usage_rows = db.execute(
        select(RuleResult.rule_version_id, func.count(distinct(RuleResult.run_id)),
               func.count(distinct(ValidationRun.application_id)))
        .join(ValidationRun, ValidationRun.id == RuleResult.run_id)
        .where(RuleResult.run_id.in_(window_runs))
        .group_by(RuleResult.rule_version_id)
    ).all()
    outcomes: dict[str, Counter] = defaultdict(Counter)
    for vid, outcome, n in db.execute(
        select(RuleResult.rule_version_id, RuleResult.outcome, func.count())
        .where(RuleResult.run_id.in_(latest_run_ids(scope, in_window=True)))
        .group_by(RuleResult.rule_version_id, RuleResult.outcome)
    ).all():
        outcomes[vid][outcome] = int(n)
    versions = {
        v.id: v for v in db.execute(
            select(RuleVersion).where(RuleVersion.id.in_([r[0] for r in usage_rows]))
        ).scalars()
    } if usage_rows else {}
    usage = sorted(
        (
            {
                "rule_id": versions[vid].rule_id,
                "rule_key": versions[vid].rule.key,
                "rule_name": versions[vid].rule.name,
                "version_id": vid,
                "version_number": versions[vid].version_number,
                "status": versions[vid].status,
                "effective_from": versions[vid].effective_from.isoformat(),
                "effective_to": versions[vid].effective_to.isoformat() if versions[vid].effective_to else None,
                "runs": int(runs),
                "applications": int(n_apps),
                "latest_outcomes": dict(outcomes.get(vid, {})),
            }
            for vid, runs, n_apps in usage_rows
            if vid in versions
        ),
        key=lambda r: (r["rule_key"], -r["version_number"]),
    )
    total = db.execute(select(func.count()).select_from(window_runs.subquery())).scalar_one()
    history = db.execute(
        select(ValidationRun, Application.reference)
        .join(Application, Application.id == ValidationRun.application_id)
        .where(ValidationRun.id.in_(window_runs))
        .order_by(ValidationRun.created_at.desc(), ValidationRun.id.desc())
        .limit(limit).offset(offset)
    ).all()
    return {
        "scope": scope.describe(),
        "version_usage": usage,
        "runs": {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [
                {
                    "run_id": run.id,
                    "application_id": run.application_id,
                    "application_reference": ref,
                    "created_at": run.created_at.isoformat(),
                    "evaluation_date": run.evaluation_date.isoformat(),
                    "trigger": run.trigger,
                    "previous_run_id": run.previous_run_id,
                    "summary": run.summary,
                    "rule_versions": len(run.rule_versions),
                    "created_by": run.created_by.full_name,
                }
                for run, ref in history
            ],
        },
    }


# ------------------------------------------------------------------ rule governance history


def governance_events(db: Session, scope: Scope, rule_id: str | None) -> list[dict]:
    """Lifecycle events derived from the rule_versions record, newest first. Rules are global, not app-scoped."""
    stmt = select(RuleVersion)
    if rule_id:
        stmt = stmt.where(RuleVersion.rule_id == rule_id)
    events: list[dict] = []

    def person(u: User | None) -> dict | None:
        return {"id": u.id, "full_name": u.full_name, "email": u.email} if u else None

    for v in db.execute(stmt).scalars():
        base = {"rule_id": v.rule_id, "rule_key": v.rule.key, "rule_name": v.rule.name, "version_id": v.id,
                "version_number": v.version_number, "current_status": v.status, "content_hash": v.content_hash}
        events.append({**base, "event": "created", "at": v.created_at, "actor": person(v.created_by),
                       "detail": v.change_summary or None})
        if v.submitted_at:
            events.append({**base, "event": "submitted", "at": v.submitted_at, "actor": person(v.submitted_by),
                           "detail": v.source_reference or None})
        if v.reviewed_at:
            kind = "rejected" if v.status == "rejected" else "approved"
            reviewer = v.reviewed_by_id
            events.append({
                **base, "event": kind, "at": v.reviewed_at, "actor": person(v.reviewed_by), "detail": v.review_note,
                "four_eyes": reviewer not in (v.created_by_id, v.submitted_by_id),
            })
        if v.retired_at:
            events.append({**base, "event": "retired", "at": v.retired_at, "actor": person(v.retired_by),
                           "detail": v.retire_reason})
    events = [e for e in events if scope.start <= e["at"] < scope.end]
    events.sort(key=lambda e: (e["at"], e["version_id"], e["event"]), reverse=True)
    for e in events:
        e["at"] = e["at"].isoformat()
        e.setdefault("four_eyes", None)
    return events


def governance(db: Session, scope: Scope, rule_id: str | None, *, limit: int, offset: int) -> dict:
    events = governance_events(db, scope, rule_id)
    rules_q = db.execute(select(Rule.id, Rule.key, Rule.name).order_by(Rule.key)).all()
    return {
        "scope": scope.describe(),
        "total": len(events),
        "limit": limit,
        "offset": offset,
        "counts": dict(Counter(e["event"] for e in events)),
        "items": events[offset: offset + limit],
        "rules": [{"id": i, "key": k, "name": n} for i, k, n in rules_q],
    }
