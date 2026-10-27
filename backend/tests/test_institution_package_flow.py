"""Exercise a prepared institution package through intake, extraction, evidence and rules."""

import hashlib
from datetime import date
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.core.config import get_settings
from app.core.roles import Role
from app.extraction.definitions import load_definitions
from app.extraction.ocr import UnavailableOcrEngine
from app.extraction.pipeline import run as extract_document
from app.models.application import Application
from app.models.evidence import EvidenceAnalysis, EvidenceFinding
from app.models.review import ReviewItem
from app.models.rules import RuleResult, ValidationRun
from app.models.trust import TrustVerification
from app.services import application_service, processing, review_service, rule_service
from app.services.audit_service import AuditContext

PACKAGES = Path(__file__).resolve().parents[2] / "mock-aicte-portal" / "institution_packages"
ASTER = PACKAGES / "Aster Valley Institute of Technology" / "02 - Extension of Approval (EoA)"
HARBOR = PACKAGES / "Harborview Institute of Engineering" / "02 - Extension of Approval (EoA)"
HARBOR_APPS = sorted((PACKAGES / "Harborview Institute of Engineering").glob("[0-9][0-9] - *"))
TRUST = Path(__file__).resolve().parents[1] / "var" / "institution-trust"


@pytest.mark.skipif(not HARBOR_APPS, reason="Harborview records are not installed")
def test_signed_institution_pdf_free_xref_does_not_trigger_review():
    document = next((PACKAGES / "Harborview Institute of Engineering").rglob("affiliation.pdf"))
    inspection = processing._inspect_pdf(document.read_bytes())
    status, findings = processing.assess(inspection, ocr=False)
    assert inspection["unreadable_objects"] == 0
    assert status == "ready"
    assert not any(f["code"] == "pdf_unreadable_objects" for f in findings)


@pytest.mark.skipif(not HARBOR_APPS, reason="Harborview records are not installed")
def test_harborview_package_has_no_spurious_missing_fields_or_review_flags():
    definitions, _ = load_definitions()
    for document in (PACKAGES / "Harborview Institute of Engineering").rglob("*.pdf"):
        result = extract_document(document.read_bytes(), "application/pdf", document.stem,
                                  definitions, UnavailableOcrEngine(), 0)
        assert result.summary["fields"]["missing"] == 0, document
        assert not result.needs_review, (document, result.summary["fields_needing_attention"])


@pytest.mark.skipif(not ASTER.is_dir() or not HARBOR.is_dir(), reason="Prepared institution packages are not installed")
@pytest.mark.parametrize("package,problem", [(ASTER, False), (ASTER, True)] +
                         [(package, False) for package in HARBOR_APPS])
def test_prepared_package_passes_intake_checks(client, make_user, session_factory, package, problem):
    owner = make_user(Role.REVIEWER, email="package-intake@example.org")
    reviewer = make_user(Role.REVIEWER, email="package-reviewer@example.org")
    auditor = make_user(Role.AUDITOR, email="package-auditor@example.org")
    manager = make_user(Role.COMPLIANCE_MANAGER, email="package-manager@example.org")
    approver = make_user(Role.SECOND_APPROVER, email="package-approver@example.org")
    settings = get_settings()
    previous = (settings.portal_shared_secret, settings.portal_owner_email,
                settings.trust_roots_dir, settings.trust_crl_dir)
    settings.portal_shared_secret = SecretStr("package-test-secret")
    settings.portal_owner_email = owner.email
    if package in HARBOR_APPS:
        settings.trust_roots_dir = TRUST / "roots"
        settings.trust_crl_dir = TRUST / "crls"
    prefix = "/api/v1/portal-intake/submissions"
    headers = {"X-Portal-Secret": "package-test-secret"}
    docs = [(path.stem, path, path.read_bytes()) for path in sorted(package.glob("*.pdf"))]
    inputs = (package / "input.txt").read_text(encoding="utf-8").splitlines()
    category_id = next(line.split(": ", 1)[1] for line in inputs if line.startswith("CATEGORY ID: "))
    category_name = next(line.split(": ", 1)[1] for line in inputs if line.startswith("APPLICATION: "))
    slug = "harbor" if package == HARBOR else "aster"
    if package in HARBOR_APPS:
        slug = "harbor"
    portal_id = f"{slug}-{category_id}-package-test"
    payload = {
        "portal_application_id": portal_id, "submission_version": 1,
        "reference": f"EDU-2026-{slug.upper()}-{category_id.upper()}", "category_id": category_id,
        "category_name": category_name,
        "institution": {"id": slug, "name": package.parent.name},
        "form": {"programme": "Computer Science and Engineering", "academic_year": "2026-27"},
        "submitted_at": "2026-10-26T00:00:00+00:00",
        "documents": [
            {"version_id": f"{slug}-version-{index}", "document_id": f"{slug}-document-{index}",
             "code": code, "version": 1, "filename": path.name, "mime": "application/pdf",
             "sha256": hashlib.sha256(content).hexdigest()}
            for index, (code, path, content) in enumerate(docs)
        ],
    }
    try:
        with session_factory() as db:
            checks = [
                ("package_document_count", "application.document_count", 2),
                ("package_institution_name", "evidence.institution_name.outcome", "pass"),
                ("package_institution_reference", "evidence.institution_reference.outcome", "pass"),
            ]
            if problem:
                checks.append(("package_manual_review", "application.document_count", 99))
            for key, field, value in checks:
                condition = {"field": field, "op": "gte" if isinstance(value, int) else "eq", "value": value}
                rule = rule_service.create_rule(
                    db, AuditContext(actor=manager), manager, key=key, name=key.replace("_", " "),
                    description="Institution intake consistency", category="aicte", owner_id=None,
                    definition={"condition": condition, "severity": "medium", "on_violation": "review",
                                "missing_data_policy": "insufficient", "low_confidence_policy": "evaluate"},
                    effective_from=date(2026, 1, 1), effective_to=None,
                    source_reference="Institutional intake data quality standard, 2026",
                    change_summary="Initial check",
                )
                version = rule.versions[-1]
                rule_service.submit(db, AuditContext(actor=manager), manager, rule.id, version.id)
                rule_service.approve(db, AuditContext(actor=approver), approver, rule.id, version.id,
                                     "Independent review completed")
        staged = client.post(prefix, json=payload, headers=headers)
        assert staged.status_code == 200, staged.text
        for index, (_, _, content) in enumerate(docs):
            uploaded = client.put(prefix + f"/{portal_id}/1/documents/{slug}-version-{index}",
                                  content=content, headers=headers)
            assert uploaded.status_code == 200, uploaded.text
        completed = client.post(prefix + f"/{portal_id}/1/complete", headers=headers)
        assert completed.status_code == 200, completed.text
        evaluated = client.post(prefix + f"/{portal_id}/1/evaluate", headers=headers)
        assert evaluated.status_code == 200, evaluated.text
        assert evaluated.json()["state"] == "complete", evaluated.json()
        receipt = client.get(prefix + f"/{portal_id}/1", headers=headers)
        assert receipt.status_code == 200, receipt.text
        assert receipt.json()["assigned_reviewer"] == reviewer.full_name
        with session_factory() as db:
            app_id = staged.json()["application_id"]
            analysis = db.scalar(select(EvidenceAnalysis).where(EvidenceAnalysis.application_id == app_id,
                                                                 EvidenceAnalysis.is_current.is_(True)))
            findings = {f.group_key: f.outcome for f in db.scalars(
                select(EvidenceFinding).where(EvidenceFinding.analysis_id == analysis.id))}
            assert findings["institution_name"] == "pass"
            assert findings["institution_reference"] == "pass"
            verifications = list(db.scalars(select(TrustVerification).where(
                TrustVerification.application_id == app_id)))
            assert len(verifications) == len(docs)
            if package in HARBOR_APPS:
                for verification in verifications:
                    states = {check["dimension"]: check["state"] for check in verification.checks}
                    for dimension in ("signature_integrity", "certificate_trust", "revocation", "timestamp"):
                        assert states[dimension] == "verified"
            run = db.scalar(select(ValidationRun).where(ValidationRun.application_id == app_id)
                            .order_by(ValidationRun.created_at.desc()))
            results = list(db.scalars(select(RuleResult).where(RuleResult.run_id == run.id)))
            assert len(results) == (4 if problem else 3)
            assert {r.outcome for r in results} == ({"pass", "review"} if problem else {"pass"})
            app = db.get(Application, app_id)
            assert reviewer.id in app.editor_ids()
            if problem:
                finding = db.scalar(select(ReviewItem).where(ReviewItem.application_id == app_id,
                    ReviewItem.assignee_id == reviewer.id))
                assert finding is not None
                assert "complete" not in application_service.allowed_actions(db, reviewer, app)
                review_service.act(db, AuditContext(actor=reviewer), reviewer, finding.id,
                    review_service.ActionIn(action="escalated", expected_version=finding.version,
                        reason="Document count needs compliance review"))
                db.refresh(finding)
                review_service.act(db, AuditContext(actor=manager), manager, finding.id,
                    review_service.ActionIn(action="dismissed", expected_version=finding.version,
                        reason="The additional document count is not required for this application"))
            assert "complete" in application_service.allowed_actions(db, reviewer, app)
            assert "complete" not in application_service.allowed_actions(db, manager, app)
            application_service.transition(db, AuditContext(actor=reviewer), reviewer, app_id,
                                           "complete", "Documents and evidence reviewed")
            assert app.review_stage == "audit" and app.status == "needs_review"
            application_service.transition(db, AuditContext(actor=auditor), auditor, app_id,
                                           "approve", "Independent document review confirmed")
            assert app.review_stage == "approved" and app.status == "completed"
        receipt = client.get(prefix + f"/{portal_id}/1", headers=headers)
        assert receipt.json()["review_stage"] == "approved"
    finally:
        (settings.portal_shared_secret, settings.portal_owner_email,
         settings.trust_roots_dir, settings.trust_crl_dir) = previous
