"""Institutional application catalogue. No entry asserts an official AICTE requirement."""
from datetime import date
import os

FIELDS = {
    "programme": ("Programme / course", "text", True),
    "level": ("Programme level", "select", True, ["Diploma", "Undergraduate", "Postgraduate"]),
    "current_intake": ("Current approved intake", "number", False),
    "proposed_intake": ("Proposed intake", "number", False),
    "approval_ref": ("Existing approval reference", "text", False),
    "academic_year": ("Proposed academic year", "text", True),
    "new_name": ("Proposed institution name", "text", False),
    "new_location": ("Proposed site / location", "textarea", False),
    "new_affiliation": ("Proposed affiliating university", "text", False),
    "effective_date": ("Proposed effective date", "date", False),
    "justification": ("Proposal and justification", "textarea", True),
}

def category(id, name, description, notes, fields, docs):
    return dict(id=id, name=name, description=description, notes=notes,
                fields=fields, docs=docs)

# Document codes: registration, approval, land, building, safety, faculty,
# programme, infrastructure, library, affiliation, finance, declaration, explanation.
CATEGORIES = [
    category("new", "New Technical Institution", "Set up a new technical institution.", "Eligibility depends on applicable regulatory requirements.", ["programme", "level", "proposed_intake", "academic_year", "justification"], ["registration", "land", "building", "safety", "faculty", "programme", "infrastructure", "library", "finance", "declaration"]),
    category("eoa", "Extension of Approval (EoA)", "Continue an existing institution's approval cycle.", "An existing approval reference is expected.", ["approval_ref", "programme", "level", "current_intake", "academic_year", "justification"], ["approval", "faculty", "programme", "infrastructure", "declaration"]),
    category("intake-up", "Increase in approved intake", "Propose a higher intake for a programme.", "Current and proposed intake should be supplied.", ["approval_ref", "programme", "level", "current_intake", "proposed_intake", "academic_year", "justification"], ["approval", "programme", "faculty", "infrastructure", "declaration"]),
    category("intake-down", "Reduction in approved intake", "Propose a lower intake for a programme.", "Current and proposed intake should be supplied.", ["approval_ref", "programme", "current_intake", "proposed_intake", "academic_year", "justification"], ["approval", "programme", "explanation", "declaration"]),
    category("new-course", "New programme or course", "Introduce a programme at an existing institution.", "Existing approval is recorded for context.", ["approval_ref", "programme", "level", "proposed_intake", "academic_year", "justification"], ["approval", "programme", "faculty", "infrastructure", "affiliation", "declaration"]),
    category("new-level", "New programme level", "Introduce a new level of study.", "Specify the intended level and programme.", ["approval_ref", "programme", "level", "proposed_intake", "academic_year", "justification"], ["approval", "programme", "faculty", "infrastructure", "declaration"]),
    category("name", "Change of institution name", "Request a change to the registered institution name.", "The proposed name must match supporting records.", ["approval_ref", "new_name", "effective_date", "justification"], ["approval", "registration", "explanation", "declaration"]),
    category("site", "Change of site or location", "Propose relocating an institution.", "Provide supporting location evidence.", ["approval_ref", "new_location", "effective_date", "justification"], ["approval", "land", "building", "safety", "explanation", "declaration"]),
    category("closure", "Closure of a programme or course", "Propose closure of a named programme.", "Describe student transition arrangements in the justification.", ["approval_ref", "programme", "current_intake", "effective_date", "justification"], ["approval", "programme", "explanation", "declaration"]),
    category("restore", "Restoration or reactivation", "Request restoration of an eligible programme or intake.", "Eligibility is subject to officer review.", ["approval_ref", "programme", "proposed_intake", "academic_year", "justification"], ["approval", "programme", "faculty", "infrastructure", "explanation", "declaration"]),
    category("affiliation", "Change of affiliating university", "Record a proposed change in affiliation.", "Subject to applicable external affiliation processes.", ["approval_ref", "new_affiliation", "effective_date", "justification"], ["approval", "affiliation", "explanation", "declaration"]),
    category("other", "Other application type", "Describe another institutional change for review.", "The applicable category is determined during review.", ["programme", "academic_year", "justification"], ["explanation", "declaration"]),
]

DOC_TYPES = {
    "registration": "Registration / incorporation evidence", "approval": "Existing approval letter or reference",
    "land": "Land ownership or lease evidence", "building": "Building plan or occupancy evidence",
    "safety": "Fire and safety evidence", "faculty": "Faculty qualifications summary",
    "programme": "Programme and intake details", "infrastructure": "Infrastructure and laboratory inventory",
    "library": "Library resources statement", "affiliation": "Affiliation evidence",
    "finance": "Audited financial information", "declaration": "Institutional declaration",
    "explanation": "Supporting explanation or justification",
}

def requirements(category_id):
    cat = next((c for c in CATEGORIES if c["id"] == category_id), None)
    if not cat:
        return []
    # Every category has a practical minimum, with other items optional
    # or conditional. This is not an interpretation of the handbook.
    result = []
    for code in cat["docs"]:
        flag = "required" if code in ("declaration", "programme", "explanation") else "optional"
        if code in ("land", "building", "safety", "affiliation", "finance"):
            flag = "conditional"
        result.append(dict(id=f"{category_id}:{code}", category_id=category_id,
                           code=code, name=DOC_TYPES[code], description=f"Supporting evidence for {DOC_TYPES[code].lower()}.",
                           flag=flag, condition="When applicable to the proposal" if flag == "conditional" else "",
                           allowed="PDF, PNG, JPG", max_mb=int(os.environ.get("MAX_UPLOAD_MB","8")), source="Institutional application checklist",
                           version="internal-1", reviewed=date.today().isoformat()))
    return result

def field_spec(key):
    raw = FIELDS[key]
    return dict(key=key, label=raw[0], type=raw[1], required=raw[2], options=raw[3] if len(raw)>3 else [])

def field_required(category_id,key):
    if key in ("programme","level","academic_year","justification","new_name","new_location","new_affiliation","effective_date"):
        return True
    if key=="approval_ref": return category_id not in ("new","other")
    if key=="current_intake": return category_id in ("intake-up","intake-down","closure")
    if key=="proposed_intake": return category_id in ("new","intake-up","intake-down","new-course","new-level","restore")
    return False

def get_category(category_id):
    return next((c for c in CATEGORIES if c["id"] == category_id), None)
