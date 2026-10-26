"""Evidence context for AI explanations, built only from stored records, and validation of the references a model
returns.

Every record has an id of the form ``<kind>:<32-hex id>`` naming a real database row: a rule result, the rule
version it ran, an extracted field, a human correction, an evidence finding or an evidence reference. The model
may cite only these ids. ``verify_references`` then checks each cited id twice, against the set that was sent and
against the database (the row exists and belongs to the same application), so a hallucinated, mistyped or
cross-application id is caught even if it happens to look valid.

Records also carry a deterministic, template-built explanation of the same result (``Context.fallback``), shown
when AI is off or its output is rejected.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assist import egress
from app.core.config import Settings
from app.core.errors import NotFoundError
from app.extraction.definitions import load_definitions
from app.models.application import Application, Document
from app.models.evidence import EvidenceAnalysis, EvidenceFinding, EvidenceReference
from app.models.extraction import ExtractedField, FieldCorrection
from app.models.rules import RuleResult, RuleVersion, ValidationRun
from app.models.user import User
from app.rules.schema import parse_definition
from app.rules.summary import definition_summary
from app.services import application_service, review_service

KINDS = ("rule_result", "rule_version", "field", "correction", "finding", "evidence_ref")
REF_RE = re.compile(r"^(" + "|".join(KINDS) + r"):([0-9a-f]{32})$")

REASONS = {
    "condition_met": "the rule's condition held",
    "condition_not_met": "the rule's condition did not hold",
    "missing_data": "data the rule needs was missing",
    "low_confidence": "an input had low evidence quality",
    "not_applicable": "the rule did not apply",
}


@dataclass
class Record:
    ref: str
    kind: str
    label: str  # shown locally
    lines: list[tuple[str, str]]  # (name, value) sent to the model, already filtered by the egress policy
    link: dict


@dataclass
class Context:
    application: Application
    subject_type: str
    subject_id: str
    deterministic: dict
    records: list[Record] = field(default_factory=list)
    fallback: list[dict] = field(default_factory=list)  # [{text, references: [ref]}]
    manifest: egress.Manifest | None = None

    def add(self, rec: Record) -> None:
        if all(r.ref != rec.ref for r in self.records):
            self.records.append(rec)

    @property
    def refs(self) -> set[str]:
        return {r.ref for r in self.records}

    def render(self) -> str:
        """The records as data elements. Values are escaped so they can't close their element."""
        parts = []
        for r in self.records:
            body = "\n".join(f"{name}: {egress.body(str(value))}" for name, value in r.lines)
            parts.append(f'<record id="{r.ref}" kind="{r.kind}">\n{body}\n</record>')
        return "\n\n".join(parts)


class _Values:
    """Applies the egress policy to values and document names, and counts what it withheld or masked."""

    def __init__(self, settings: Settings, manifest: egress.Manifest, docs: list[Document]) -> None:
        self.policy = settings.ai_document_egress
        self.mask_ids = settings.ai_mask_identifiers
        self.manifest = manifest
        definitions, _ = load_definitions(settings.field_definitions_path)
        self.types = {d.key: d.type.value for d in definitions.fields}
        self.labels = {d.key: d.label for d in definitions.fields}
        self.doc_index = {d.id: i + 1 for i, d in enumerate(sorted(docs, key=lambda d: (d.created_at, d.id)))}
        self.doc_names = {d.id: d.original_filename for d in docs}

    @property
    def values_allowed(self) -> bool:
        return egress.allows(self.policy, "extracted_values")

    def doc(self, document_id: str | None) -> str:
        """Local display name."""
        return self.doc_names.get(document_id or "", "a document")

    def doc_out(self, document_id: str | None) -> str:
        """Name sent to the model: file names can contain personal data, so they need the values policy."""
        if self.values_allowed:
            self.manifest.categories.add("document_names")
            return self.doc(document_id)
        self.manifest.withheld.append("document_names")
        return f"Document {self.doc_index.get(document_id or '', '?')}"

    def value_out(self, field_key: str, value: object) -> str:
        if value is None or value == "":
            return "(no value)"
        if not self.values_allowed:
            self.manifest.withheld.append("extracted_values")
            return "(withheld by policy)"
        self.manifest.categories.add("extracted_values")
        text = str(value)
        if self.mask_ids and self.types.get(field_key) in egress.MASKED_TYPES:
            self.manifest.masked_values += 1
            return egress.mask(text)
        return text

    def free_text_out(self, text: str | None) -> str | None:
        """Human-written text (correction reasons) and template explanations that embed values."""
        if not text:
            return None
        if not self.values_allowed:
            self.manifest.withheld.append("free_text")
            return None
        self.manifest.categories.add("free_text")
        return text


def _field_link(app_id: str, document_id: str | None, page: int | None, field_key: str | None) -> dict:
    return {"type": "field", "application_id": app_id, "document_id": document_id, "page_number": page,
            "field_key": field_key}


# ------------------------------------------------------------------ review items (rule results)


def review_item_context(db: Session, user: User, settings: Settings, item_id: str) -> Context:
    item, app = review_service.get_item(db, user, item_id)
    result = db.get(RuleResult, item.current_result_id)
    run = db.get(ValidationRun, item.current_run_id)
    if result is None or run is None:  # pragma: no cover - foreign keys guarantee both
        raise NotFoundError("Review item not found")
    version = next((r for r in run.rule_versions if r["version_id"] == result.rule_version_id), None) or {}
    manifest = egress.Manifest(policy=settings.ai_document_egress, categories={"rule_metadata"})
    docs = review_service.app_documents(db, app)
    values = _Values(settings, manifest, docs)

    ctx = Context(
        application=app,
        subject_type="review_item",
        subject_id=item.id,
        manifest=manifest,
        deterministic={
            "kind": "rule_result",
            "outcome": result.outcome,
            "severity": result.severity,
            "reason": result.reason,
            "message": result.message,
            "low_confidence": result.low_confidence,
            "evaluation_date": run.evaluation_date.isoformat(),
            "run_id": run.id,
            "review_status": item.status,
            "rule": {
                "rule_id": result.rule_id,
                "key": result.rule_key,
                "name": result.rule_name,
                "version_id": result.rule_version_id,
                "version_number": result.version_number,
                "source_reference": version.get("source_reference"),
            },
        },
    )
    rr_ref = f"rule_result:{result.id}"
    rv_ref = f"rule_version:{result.rule_version_id}"
    summary = {}
    try:
        summary = definition_summary(parse_definition(version.get("definition") or {}))
    except Exception:  # noqa: BLE001 - a definition that no longer parses is described without its summary
        summary = {}

    checks = []
    for t in result.trace:
        missing = " (no usable value)" if t.get("missing") or not t.get("observations") else ""
        checks.append(
            f"{t.get('path')}: {t.get('field')} {t.get('op')} {t.get('expected')!r} -> {t.get('result')}{missing}"
        )
    ctx.add(Record(
        ref=rr_ref, kind="rule_result", label=f"Result of “{result.rule_name}” in validation run",
        link={"type": "rule_result", "application_id": app.id, "run_id": run.id},
        lines=[
            ("rule", f"{result.rule_key} — {result.rule_name}"),
            ("rule version", str(result.version_number)),
            ("evaluation date", run.evaluation_date.isoformat()),
            ("outcome", result.outcome),
            ("severity", result.severity),
            ("reason", f"{result.reason} ({REASONS.get(result.reason, result.reason.replace('_', ' '))})"),
            ("rule message", result.message or "(none)"),
            ("low-confidence input", "yes" if result.low_confidence else "no"),
            *[(f"check {i + 1}", c) for i, c in enumerate(checks)],
        ],
    ))
    ctx.add(Record(
        ref=rv_ref, kind="rule_version", label=f"“{result.rule_name}” version {result.version_number}",
        link={"type": "rule_version", "rule_id": result.rule_id, "version_id": result.rule_version_id},
        lines=[
            ("rule", f"{result.rule_key} — {result.rule_name}"),
            ("version", str(result.version_number)),
            ("source reference", version.get("source_reference") or "(none recorded)"),
            ("effective", f"from {version.get('effective_from')} to {version.get('effective_to') or 'open-ended'}"),
            ("condition", summary.get("condition", "(unavailable)")),
            ("applies when", summary.get("applies_when", "(unavailable)")),
            ("policies", summary.get("policies", "(unavailable)")),
        ],
    ))
    ctx.fallback.append({
        "text": f"Rule “{result.rule_name}” (version {result.version_number}) returned “{result.outcome}” with "
        f"{result.severity} severity on {run.evaluation_date.isoformat()}: "
        f"{REASONS.get(result.reason, result.reason.replace('_', ' '))}.",
        "references": [rr_ref, rv_ref],
    })
    if result.message:
        ctx.fallback.append({"text": f"The rule's message: {result.message}", "references": [rr_ref]})

    for t in result.trace:
        if t.get("missing") or not t.get("observations"):
            ctx.fallback.append({
                "text": f"No usable value was available for {t.get('field')}, so this check could not be decided "
                "from evidence.",
                "references": [rr_ref],
            })
        for o in t.get("observations", []):
            if o.get("kind") == "extracted" and o.get("field_id"):
                key = o.get("field_key") or ""
                label = values.labels.get(key, key)
                f_ref = f"field:{o['field_id']}"
                refs = [f_ref]
                ctx.add(Record(
                    ref=f_ref, kind="field", label=f"{label} — {values.doc(o.get('document_id'))}",
                    link=_field_link(app.id, o.get("document_id"), o.get("page_number"), key),
                    lines=[
                        ("document", values.doc_out(o.get("document_id"))),
                        ("field", f"{label} ({key})"),
                        ("page", str(o.get("page_number") or "unknown")),
                        ("value used by the rule", values.value_out(key, o.get("value"))),
                        ("value source", o.get("value_source") or "extraction"),
                        ("evidence quality", o.get("quality") or "unknown"),
                    ],
                ))
                if o.get("correction_id"):
                    c_ref = f"correction:{o['correction_id']}"
                    refs.append(c_ref)
                    corr = db.get(FieldCorrection, o["correction_id"])
                    lines = [("field", f"{label} ({key})"), ("document", values.doc_out(o.get("document_id"))),
                             ("corrected value", values.value_out(key, corr.normalized_value if corr else None))]
                    reason = values.free_text_out(corr.reason if corr else None)
                    if reason:
                        lines.append(("reason given", reason))
                    ctx.add(Record(
                        ref=c_ref, kind="correction",
                        label=f"Correction of {label} — {values.doc(o.get('document_id'))}",
                        link=_field_link(app.id, o.get("document_id"), o.get("page_number"), key), lines=lines,
                    ))
                source = " (from a human correction)" if o.get("correction_id") else ""
                ctx.fallback.append({
                    "text": f"{label} on {values.doc(o.get('document_id'))}"
                    f"{', page ' + str(o['page_number']) if o.get('page_number') else ''} was “{o.get('value')}”"
                    f"{source}; evidence quality {o.get('quality') or 'unknown'}.",
                    "references": refs,
                })
            elif o.get("kind") == "evidence" and o.get("finding_id"):
                finding = db.get(EvidenceFinding, o["finding_id"])
                if finding is not None:
                    _add_finding(ctx, values, finding, include_refs=False)
                    ctx.fallback.append({
                        "text": f"The cross-document check “{finding.group_label}” was “{finding.outcome}”"
                        f"{' (the analysis was stale at validation time)' if o.get('stale') else ''}.",
                        "references": [f"finding:{finding.id}"],
                    })
    return ctx


# ------------------------------------------------------------------ evidence findings


def _add_finding(ctx: Context, values: _Values, finding: EvidenceFinding, *, include_refs: bool) -> None:
    rels = [
        f"{rel.result} ({rel.reason.replace('_', ' ')}, method {rel.method}"
        f"{', evidence quality ' + rel.evidence_quality if rel.evidence_quality else ''})"
        for rel in finding.relationships
    ]
    lines = [
        ("check", f"{finding.group_label} ({finding.group_key})"),
        ("outcome", finding.outcome),
        ("severity", finding.severity),
        ("evidence quality", finding.evidence_quality or "n/a"),
        ("documents compared", str(len(finding.references))),
        *[(f"comparison {i + 1}", r) for i, r in enumerate(rels)],
    ]
    explanation = values.free_text_out(finding.explanation)
    if explanation:
        lines.append(("stored explanation", explanation))
    ctx.add(Record(
        ref=f"finding:{finding.id}", kind="finding", label=f"Cross-document check “{finding.group_label}”",
        link={"type": "finding", "application_id": ctx.application.id, "finding_id": finding.id},
        lines=lines,
    ))
    if not include_refs:
        return
    for ref in finding.references:
        ctx.add(Record(
            ref=f"evidence_ref:{ref.id}", kind="evidence_ref", label=f"{ref.field_label} — {ref.document_name}",
            link=_field_link(ctx.application.id, ref.document_id, ref.page_number, ref.field_key),
            lines=[
                ("document", values.doc_out(ref.document_id)),
                ("field", f"{ref.field_label} ({ref.field_key})"),
                ("page", str(ref.page_number or "unknown")),
                ("value compared", values.value_out(ref.field_key, ref.effective_value)),
                ("status", ref.status),
                ("value source", ref.value_source),
                ("evidence quality", ref.evidence_quality),
                ("usable", "yes" if ref.usable else "no"),
            ],
        ))


def finding_context(db: Session, user: User, settings: Settings, finding_id: str) -> Context:
    finding = db.get(EvidenceFinding, finding_id)
    analysis = db.get(EvidenceAnalysis, finding.analysis_id) if finding else None
    if finding is None or analysis is None:
        raise NotFoundError("Finding not found")
    try:
        app = application_service.get_for_read(db, user, analysis.application_id)
    except NotFoundError:
        raise NotFoundError("Finding not found") from None
    manifest = egress.Manifest(policy=settings.ai_document_egress, categories={"finding_metadata"})
    values = _Values(settings, manifest, review_service.app_documents(db, app))
    ctx = Context(
        application=app,
        subject_type="evidence_finding",
        subject_id=finding.id,
        manifest=manifest,
        deterministic={
            "kind": "evidence_finding",
            "outcome": finding.outcome,
            "severity": finding.severity,
            "evidence_quality": finding.evidence_quality,
            "group_key": finding.group_key,
            "group_label": finding.group_label,
            "analysis_id": analysis.id,
            "analysis_is_current": analysis.is_current,
            "priority_score": finding.priority_score,
        },
    )
    _add_finding(ctx, values, finding, include_refs=True)
    f_ref = f"finding:{finding.id}"
    ctx.fallback.append({"text": finding.explanation, "references": [f_ref]})
    by_id = {r.id: r for r in finding.references}
    for rel in finding.relationships:
        refs = [f"evidence_ref:{i}" for i in (rel.source_reference_id, rel.target_reference_id) if i in by_id]
        ctx.fallback.append({"text": rel.explanation, "references": [f_ref, *refs]})
    return ctx


# ------------------------------------------------------------------ whole application

_SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}
_MAX_RESULT_RECORDS = 25
_MAX_FINDING_RECORDS = 15


def application_context(db: Session, user: User, settings: Settings, application_id: str) -> Context:
    """The latest validation results and the current cross-document findings of one application.

    Access is the ordinary application read check, so another institution's application is "not found". Only
    results that need a person (anything but a pass) are sent as records; passes are counted in the deterministic
    block so the summary can say how many were fine without sending their content.
    """
    app = application_service.get_for_read(db, user, application_id)
    docs = review_service.app_documents(db, app)
    manifest = egress.Manifest(policy=settings.ai_document_egress, categories={"rule_metadata", "finding_metadata"})
    values = _Values(settings, manifest, docs)

    run = db.execute(
        select(ValidationRun).where(ValidationRun.application_id == app.id).order_by(ValidationRun.created_at.desc())
    ).scalars().first()
    analysis = db.execute(
        select(EvidenceAnalysis).where(EvidenceAnalysis.application_id == app.id, EvidenceAnalysis.is_current.is_(True))
    ).scalars().first()

    results = list(run.results) if run else []
    need_attention = [r for r in results if r.outcome not in ("pass", "not_applicable", "not_in_force")]
    need_attention.sort(key=lambda r: (-_SEVERITY_RANK.get(r.severity, 0), r.position))
    findings = [f for f in (analysis.findings if analysis else []) if f.outcome != "pass"]
    findings.sort(key=lambda f: (-f.priority_score, f.group_key))

    outcome_counts: dict[str, int] = {}
    for r in results:
        outcome_counts[r.outcome] = outcome_counts.get(r.outcome, 0) + 1
    finding_counts: dict[str, int] = {}
    for f in (analysis.findings if analysis else []):
        finding_counts[f.outcome] = finding_counts.get(f.outcome, 0) + 1

    if run is None and analysis is None:
        overall = "not_validated"
    elif outcome_counts.get("fail") or finding_counts.get("fail"):
        overall = "failures_present"
    elif need_attention or findings:
        overall = "needs_review"
    else:
        overall = "no_issues_found"
    worst = max((r.severity for r in need_attention), key=lambda s: _SEVERITY_RANK.get(s, 0), default=None)

    ctx = Context(
        application=app,
        subject_type="application",
        subject_id=app.id,
        manifest=manifest,
        deterministic={
            "kind": "application",
            "outcome": overall,
            "severity": worst,
            "reference": app.reference,
            "status": app.status,
            "documents": len(docs),
            "validation_run_id": run.id if run else None,
            "evaluation_date": run.evaluation_date.isoformat() if run else None,
            "rule_outcomes": outcome_counts,
            "evidence_outcomes": finding_counts,
            "analysis_is_current": bool(analysis),
        },
    )

    if run is None:
        ctx.fallback.append({"text": "No validation run exists for this application yet, so no rule has been evaluated.", "references": []})
    else:
        ctx.fallback.append({
            "text": f"The latest validation run (evaluation date {run.evaluation_date.isoformat()}) evaluated "
            f"{len(results)} rule(s): " + ", ".join(f"{n} {k}" for k, n in sorted(outcome_counts.items())) + ".",
            "references": [],
        })
    for r in need_attention[:_MAX_RESULT_RECORDS]:
        ref = f"rule_result:{r.id}"
        ctx.add(Record(
            ref=ref, kind="rule_result", label=f"Result of “{r.rule_name}” in validation run",
            link={"type": "rule_result", "application_id": app.id, "run_id": run.id},
            lines=[
                ("rule", f"{r.rule_key} — {r.rule_name}"),
                ("rule version", str(r.version_number)),
                ("outcome", r.outcome),
                ("severity", r.severity),
                ("reason", f"{r.reason} ({REASONS.get(r.reason, r.reason.replace('_', ' '))})"),
                ("rule message", r.message or "(none)"),
                ("low-confidence input", "yes" if r.low_confidence else "no"),
            ],
        ))
        what = "needs a person to look at it" if r.outcome == "review" else (
            "could not be decided because evidence is missing" if r.outcome == "insufficient" else "did not pass")
        ctx.fallback.append({
            "text": f"Rule “{r.rule_name}” ({r.severity} severity) {what}: "
            f"{REASONS.get(r.reason, r.reason.replace('_', ' '))}.",
            "references": [ref],
        })
    if analysis is None:
        ctx.fallback.append({"text": "No cross-document evidence analysis has been run for this application.", "references": []})
    for f in findings[:_MAX_FINDING_RECORDS]:
        _add_finding(ctx, values, f, include_refs=False)
        ctx.fallback.append({
            "text": f"Cross-document check “{f.group_label}” is “{f.outcome}” ({f.severity} severity, priority "
            f"{f.priority_score}).",
            "references": [f"finding:{f.id}"],
        })
    if len(need_attention) > _MAX_RESULT_RECORDS or len(findings) > _MAX_FINDING_RECORDS:
        manifest.truncated = True
    return ctx


# ------------------------------------------------------------------ reference validation


def parse_ref(ref: str) -> tuple[str, str] | None:
    m = REF_RE.match(ref.strip())
    return (m.group(1), m.group(2)) if m else None


def _owner_application(db: Session, kind: str, row_id: str) -> str | None:
    """The application a referenced row belongs to, or None if the row doesn't exist."""
    if kind == "rule_result":
        rr = db.get(RuleResult, row_id)
        run = db.get(ValidationRun, rr.run_id) if rr else None
        return run.application_id if run else None
    if kind == "rule_version":
        if db.get(RuleVersion, row_id) is None:
            return None
        # A rule version isn't owned by an application; it belongs to one if a run of it there produced a result.
        row = db.execute(
            select(ValidationRun.application_id)
            .join(RuleResult, RuleResult.run_id == ValidationRun.id)
            .where(RuleResult.rule_version_id == row_id)
        ).first()
        return row[0] if row else ""
    if kind in ("field", "correction"):
        model = ExtractedField if kind == "field" else FieldCorrection
        obj = db.get(model, row_id)
        doc = db.get(Document, obj.document_id) if obj else None
        return doc.application_id if doc else None
    if kind == "finding":
        f = db.get(EvidenceFinding, row_id)
        a = db.get(EvidenceAnalysis, f.analysis_id) if f else None
        return a.application_id if a else None
    if kind == "evidence_ref":
        r = db.get(EvidenceReference, row_id)
        f = db.get(EvidenceFinding, r.finding_id) if r else None
        a = db.get(EvidenceAnalysis, f.analysis_id) if f else None
        return a.application_id if a else None
    return None  # pragma: no cover - REF_RE only admits KINDS


def verify_references(db: Session, application_id: str, refs: list[str], allowed: set[str]) -> dict[str, str]:
    """Map each cited reference to "ok" or the reason it was rejected."""
    out: dict[str, str] = {}
    for ref in refs:
        if ref in out:
            continue
        parsed = parse_ref(ref)
        if parsed is None:
            out[ref] = "malformed"
            continue
        owner = _owner_application(db, *parsed)
        if owner is None:
            out[ref] = "not_found"
        elif owner != application_id:
            out[ref] = "other_application"
        elif ref not in allowed:
            out[ref] = "not_in_context"
        else:
            out[ref] = "ok"
    return out
