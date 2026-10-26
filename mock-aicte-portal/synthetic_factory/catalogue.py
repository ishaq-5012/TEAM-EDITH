"""APH traceability and clearly separated demonstration requirements."""

from datetime import date

HANDBOOK_URL = "https://aicte-qa.aicte-india.org/sites/default/files/APH%20Final.pdf"
RULE_VERSION = "AICTE APH 2024-2027 (category reference); DEMO-1 document templates"
REVIEWED = "2026-10-25"

# These clauses verify that the *kind of application* appears in the handbook.
# They are not a claim that our demo forms are official AICTE forms.
CATEGORIES = [
    ("new-institution", "New Technical Institution", "Chapter I", "new"),
    ("extension-of-approval", "Extension of Approval", "Chapter II, 2.1", "eoa"),
    ("intake-increase", "Increase in approved intake", "Chapter II, 2.6", "intake"),
    ("intake-reduction", "Reduction in approved intake", "Chapter II introduction xiv", "intake"),
    ("new-course", "Introduction of a new course", "Chapter II, 2.6", "course"),
    ("new-level", "Introduction of a new programme level", "Chapter II, 2.7", "level"),
    ("institution-name-change", "Change of institution name", "Chapter II introduction xv", "name"),
    ("site-change", "Change of site or location", "Chapter II, 2.17", "site"),
    ("course-closure", "Closure of a course", "Chapter II introduction xiv", "closure"),
    ("intake-restoration", "Restoration of eligible intake", "Chapter II, 2.16", "restoration"),
    ("affiliation-change", "Change of affiliating body details", "Chapter II introduction xv", "affiliation"),
    ("institution-merger", "Merger of institutions", "Chapter II, 2.13", "merger"),
    ("division-addition", "Addition of a division", "Annexure 2, 2.6(iii)", "division"),
    ("supernumerary-seats", "Introduction of supernumerary seats", "Chapter II introduction v", "supernumerary"),
]

# Document types are demo packages for extraction testing. No otherwise
# unverified document is represented as a mandatory official submission.
BASE = [
    ("application_form", "Main synthetic application form"),
    ("application_summary", "Application summary and proposed action"),
    ("institution_profile", "Institution identity and governing profile"),
    ("document_checklist", "Requirement and evidence checklist"),
    ("programme_schedule", "Programme and intake schedule"),
    ("faculty_master", "Faculty roster and qualifications"),
    ("staffing_summary", "Department staffing and faculty mapping"),
    ("infrastructure_inventory", "Campus rooms and laboratory inventory"),
    ("library_resources", "Library and digital resource statement"),
    ("financial_summary", "Unaudited synthetic financial schedule"),
    ("application_history", "Fictional application and approval history"),
    ("declaration", "Synthetic institution declaration"),
]

FAMILY_DOCS = {
    "new": ["new_institution_proposal", "governing_body", "campus_facilities"],
    "eoa": ["continuation_review", "computer_network"],
    "intake": ["intake_comparison", "change_justification", "management_resolution"],
    "course": ["new_course_proposal", "change_justification", "management_resolution"],
    "level": ["new_level_proposal", "change_justification"],
    "name": ["name_change_comparison", "governing_body"],
    "site": ["site_change_proposal", "campus_facilities", "safety_demo_record"],
    "closure": ["course_closure_plan", "student_continuity", "change_justification"],
    "restoration": ["restoration_timeline", "intake_comparison"],
    "affiliation": ["affiliation_change_record", "change_justification"],
    "merger": ["merger_comparison", "governing_body", "student_continuity"],
    "division": ["division_proposal", "intake_comparison", "management_resolution"],
    "supernumerary": ["supernumerary_proposal", "student_services", "management_resolution"],
}

DOC_TITLES = {**dict(BASE), **{
    "new_institution_proposal": "New institution project proposal",
    "governing_body": "Fictional governing body details",
    "campus_facilities": "Campus, building and facilities schedule",
    "continuation_review": "Continuation self-disclosure review",
    "computer_network": "Computer and network resources",
    "intake_comparison": "Existing and proposed intake comparison",
    "change_justification": "Application change justification",
    "management_resolution": "Synthetic management resolution template",
    "new_course_proposal": "New course proposal",
    "new_level_proposal": "New programme level proposal",
    "name_change_comparison": "Institution name change comparison",
    "site_change_proposal": "Site and location change proposal",
    "safety_demo_record": "Fictional safety evidence placeholder",
    "course_closure_plan": "Course closure and teach-out plan",
    "student_continuity": "Student continuity arrangements",
    "restoration_timeline": "Intake restoration timeline",
    "affiliation_change_record": "Affiliation detail change record",
    "merger_comparison": "Institution merger comparison",
    "division_proposal": "Additional division proposal",
    "supernumerary_proposal": "Supernumerary seat proposal",
    "student_services": "Student support service schedule",
}}


def category_records():
    return [dict(id=slug, name=name, family=family, source_id="APH-2024-2027",
                 source_clause=clause, verification_status="verified_category_reference",
                 applicability_note="Demo scenario; cycle-specific eligibility and amendments require review")
            for slug, name, clause, family in CATEGORIES]


def source_records():
    return [dict(id="APH-2024-2027", title="AICTE Approval Process Handbook 2024-2027",
                 url=HANDBOOK_URL, edition="2024-2027", last_reviewed=REVIEWED,
                 review_scope="Chapter I, Chapter II and Annexure 2 checked for category and selected resolution references",
                 amendment_status="Later amendments and current-cycle applicability not verified")]


def requirement_records():
    result = []
    for slug, _, clause, family in CATEGORIES:
        docs = list(dict.fromkeys([key for key, _ in BASE] + FAMILY_DOCS[family] +
                                  ["safety_demo_record", "student_services"]))
        for doc in docs:
            status = "required"
            condition = "Always for this synthetic scenario"
            if doc in {"safety_demo_record", "student_services"}:
                status = "conditional"
                condition = "Applies when the scenario includes a changed campus or supernumerary services"
            if doc == "computer_network":
                status = "optional"
                condition = "Included to exercise resource extraction"
            official = doc == "management_resolution" and slug in {
                "new-course", "division-addition"}
            result.append(dict(
                id=f"REQ-{slug.upper()}-{doc.upper()}", category_id=slug,
                document_type=doc, description=DOC_TITLES[doc], requirement_level=status,
                applicability_condition=condition,
                classification="conditional_official_reference" if official else "demo_only",
                verification_status="verified" if official else "demo_only",
                source_id="APH-2024-2027" if official else None,
                source_title="AICTE Approval Process Handbook 2024-2027" if official else None,
                source_url=HANDBOOK_URL if official else None, rule_version=RULE_VERSION,
                source_clause="Annexure 2, 2.6(iii)" if official else None,
                source_note=("Handbook mentions a resolution for additional courses/divisions; generated PDF is a visibly synthetic stand-in, not a signed submission."
                             if official else "Document form and inclusion are synthetic test design, not an official mandatory filing claim."),
                last_reviewed=REVIEWED, supported_formats=["pdf"],
                generation_instructions=f"Render a {DOC_TITLES[doc].lower()} using the fictional institution and application data.",
            ))
    return result
