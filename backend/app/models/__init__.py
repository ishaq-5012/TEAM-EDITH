"""Import every model so Alembic and metadata.create_all see the full schema."""

from app.models.ai import AIInteraction
from app.models.application import Application, ApplicationMember, Document, ProcessingJob
from app.models.audit import AuditEvent, AuditHead
from app.models.evidence import EvidenceAnalysis, EvidenceFinding, EvidenceReference, FieldRelationship
from app.models.institution import Institution
from app.models.portal_intake import PortalDocument, PortalSubmission
from app.models.extraction import DocumentPage, ExtractedField, ExtractionRun, FieldCorrection
from app.models.review import ReviewAction, ReviewItem
from app.models.rules import Rule, RuleResult, RuleTestCase, RuleVersion, ValidationRun
from app.models.session import LoginAttempt, UserSession
from app.models.trust import TrustVerification
from app.models.user import User

__all__ = [
    "AIInteraction",
    "Application",
    "ApplicationMember",
    "AuditEvent",
    "AuditHead",
    "Document",
    "EvidenceAnalysis",
    "EvidenceFinding",
    "EvidenceReference",
    "FieldRelationship",
    "DocumentPage",
    "ExtractedField",
    "ExtractionRun",
    "FieldCorrection",
    "Institution",
    "PortalDocument",
    "PortalSubmission",
    "LoginAttempt",
    "ProcessingJob",
    "ReviewAction",
    "ReviewItem",
    "Rule",
    "RuleResult",
    "RuleTestCase",
    "RuleVersion",
    "TrustVerification",
    "User",
    "UserSession",
    "ValidationRun",
]
