"""Install the institution intake quality checks in the local VerifyFlow database."""

from datetime import date

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.rules import Rule
from app.models.user import User
from app.services import rule_service
from app.services.audit_service import AuditContext


CHECKS = (
    ("institution_document_set", "Supporting document set present", {"field": "application.document_count", "op": "gte", "value": 2}),
    ("institution_name_alignment", "Institution name consistent across records", {"field": "evidence.institution_name.outcome", "op": "eq", "value": "pass"}),
    ("institution_reference_alignment", "Institution reference consistent across records", {"field": "evidence.institution_reference.outcome", "op": "eq", "value": "pass"}),
)


def main() -> None:
    with SessionLocal() as db:
        manager = db.scalar(select(User).where(User.email == "compliance.manager@example.org"))
        approver = db.scalar(select(User).where(User.email == "approver@example.com"))
        if manager is None or approver is None:
            raise RuntimeError("Required existing officer accounts are missing")
        approver.role = "second_approver"
        approver.full_name = "Independent Rule Approver"
        manager.full_name = "Compliance Manager"
        for email, name in (("reviewer.demo@example.org", "Review Officer"), ("auditor.demo@example.org", "Audit Officer")):
            user = db.scalar(select(User).where(User.email == email))
            if user:
                user.full_name = name
        db.commit()
        for key, name, condition in CHECKS:
            if db.scalar(select(Rule).where(Rule.key == key)):
                continue
            rule = rule_service.create_rule(
                db, AuditContext(actor=manager), manager,
                key=key, name=name, description="Internal intake consistency check for institutional submissions.",
                category="aicte", owner_id=None,
                definition={"condition": condition, "severity": "medium", "on_violation": "review",
                            "missing_data_policy": "insufficient", "low_confidence_policy": "evaluate",
                            "pass_message": name + ".", "fail_message": name + " requires officer review."},
                effective_from=date(2026, 1, 1), effective_to=None,
                source_reference="Institutional intake data quality standard, 2026",
                change_summary="Initial institutional intake check",
            )
            version = rule.versions[-1]
            rule_service.submit(db, AuditContext(actor=manager), manager, rule.id, version.id)
            rule_service.approve(db, AuditContext(actor=approver), approver, rule.id, version.id,
                                 "Reviewed the source, condition, and test result; approved for intake checks.")
            print(f"published {key}")


if __name__ == "__main__":
    main()
