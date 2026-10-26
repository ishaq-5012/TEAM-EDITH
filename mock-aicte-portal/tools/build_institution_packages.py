"""Prepare consistent institution-owned application inputs and supporting records."""

from __future__ import annotations

import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.catalog import CATEGORIES, DOC_TYPES, requirements

ROOT = Path(__file__).resolve().parents[1] / "institution_packages"
YEAR = "2026-27"
DATE = "2026-10-25"

INSTITUTIONS = (
    dict(name="Aster Valley Institute of Technology", username="aster_demo", ref="AVIT-REG-001",
         approval="AVIT-PRIOR-2025", programme="Computer Science and Engineering",
         address="12 Campus Road, Chennai, Tamil Nadu 600001", district="Chennai", state="Tamil Nadu",
         affiliation="South Coast Technical University", faculty=42, rooms=25),
    dict(name="Cedar Crest Polytechnic", username="cedar_demo", ref="CCP-REG-001",
         approval="CCP-PRIOR-2025", programme="Electrical Engineering",
         address="24 College Avenue, Coimbatore, Tamil Nadu 641001", district="Coimbatore", state="Tamil Nadu",
         affiliation="South Coast Technical University", faculty=38, rooms=22),
    dict(name="Meridian School of Computing", username="meridian_demo", ref="MSC-REG-001",
         approval="MSC-PRIOR-2025", programme="Information Technology",
         address="36 Knowledge Street, Madurai, Tamil Nadu 625001", district="Madurai", state="Tamil Nadu",
         affiliation="South Coast Technical University", faculty=46, rooms=28),
)

DETAILS = {
    "registration": "Institution ownership, location, management and registration references maintained by the institution.",
    "approval": "Index of the prior approval reference supplied by the institution. Original issuer confirmation remains an officer task.",
    "land": "Campus land and occupancy reference, with address matching the institution profile.",
    "building": "Building capacity and occupancy summary prepared from the institution's facilities register.",
    "safety": "Institution safety review checklist and follow-up record; external certification must be checked separately.",
    "faculty": "Faculty roster control totals and qualifications summary for the proposed programme.",
    "programme": "Programme and intake schedule for this application category.",
    "infrastructure": "Room, laboratory and equipment inventory aligned with the programme schedule.",
    "library": "Library and digital learning resources statement for the same academic year.",
    "affiliation": "Affiliation change or continuation reference supplied by the institution; issuer confirmation is separate.",
    "finance": "Institution financial information summary for the proposed cycle.",
    "declaration": "Institution submission declaration by its designated registrar.",
    "explanation": "Written rationale and transition arrangements for the requested application action.",
}


def safe_name(value: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "", value).rstrip(" .")


def fields_for(inst: dict, category: dict) -> dict[str, str]:
    code = category["id"]
    fields = {
        "programme": inst["programme"], "level": "Undergraduate", "current_intake": "120",
        "proposed_intake": "120", "approval_ref": inst["approval"], "academic_year": YEAR,
        "new_name": inst["name"] + " and Research Centre",
        "new_location": "48 Academic Way, " + inst["district"] + ", " + inst["state"],
        "new_affiliation": "Regional Technical University", "effective_date": "2027-07-01",
        "justification": f"Request for {category['name'].lower()} supported by the enclosed institution records.",
    }
    if code == "intake-up": fields["proposed_intake"] = "180"
    if code == "intake-down": fields["proposed_intake"] = "60"
    if code == "new-course": fields.update(programme="Artificial Intelligence and Data Science", proposed_intake="60")
    if code == "new-level": fields.update(level="Postgraduate", proposed_intake="24")
    if code == "restore": fields["proposed_intake"] = "120"
    if code == "new": fields["proposed_intake"] = "120"
    if code == "closure": fields["justification"] += " Current students will complete their programme through a documented teach-out plan."
    return {key: fields[key] for key in category["fields"]}


def document_facts(inst: dict, category: dict, form: dict, code: str, reference: str) -> list[tuple[str, str]]:
    facts = [
        ("Institution name", inst["name"]), ("Institution reference", inst["ref"]),
        ("Application category", category["name"]), ("Document reference", reference),
        ("Record date", DATE),
    ]
    if "approval_ref" in form: facts.append(("Existing approval reference", form["approval_ref"]))
    if "programme" in form: facts.append(("Programme / course", form["programme"]))
    if "level" in form: facts.append(("Programme level", form["level"]))
    if "current_intake" in form: facts.append(("Current intake", form["current_intake"]))
    if "proposed_intake" in form: facts.append(("Proposed intake", form["proposed_intake"]))
    if "academic_year" in form: facts.append(("Academic year", form["academic_year"]))
    if "new_name" in form: facts.append(("Proposed institution name", form["new_name"]))
    if "new_location" in form: facts.append(("Proposed site / location", form["new_location"]))
    if "new_affiliation" in form: facts.append(("Proposed affiliation", form["new_affiliation"]))
    if "effective_date" in form: facts.append(("Effective date", form["effective_date"]))
    if code in ("faculty", "registration"): facts.append(("Faculty entries", str(inst["faculty"])))
    if code in ("infrastructure", "registration"): facts.append(("Rooms and facilities", str(inst["rooms"])))
    if code in ("affiliation", "registration"): facts.append(("Affiliation", inst["affiliation"]))
    return facts


def make_pdf(path: Path, inst: dict, category: dict, form: dict, code: str, reference: str) -> None:
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="HeadingCustom", parent=styles["Heading1"], fontName="Helvetica-Bold",
                              fontSize=17, leading=21, textColor=colors.HexColor("#12324d"), spaceAfter=12))
    styles.add(ParagraphStyle(name="BodyCustom", parent=styles["BodyText"], fontSize=10, leading=15, spaceAfter=9))
    styles.add(ParagraphStyle(name="FootCustom", parent=styles["BodyText"], fontSize=8, leading=11,
                              textColor=colors.HexColor("#566b78"), alignment=TA_CENTER))
    title = DOC_TYPES[code]
    story = [Paragraph(title, styles["HeadingCustom"]),
             Paragraph(inst["name"], styles["Heading2"]), Spacer(1, 5 * mm)]
    for label, value in document_facts(inst, category, form, code, reference):
        story.append(Paragraph(f"<b>{label}:</b> {value}", styles["BodyCustom"]))
    story += [Spacer(1, 5 * mm), Paragraph("Record context", styles["Heading2"]),
              Paragraph(DETAILS[code], styles["BodyCustom"]),
              Paragraph(form.get("justification", category["description"]), styles["BodyCustom"])]
    if code == "faculty":
        story.append(Paragraph(f"Faculty entries: {inst['faculty']}; departments: 5; doctoral-qualified faculty: 12.", styles["BodyCustom"]))
    if code == "infrastructure":
        story.append(Paragraph(f"Rooms and facilities: {inst['rooms']}; laboratories: 6; networked workstations: 120.", styles["BodyCustom"]))
    if code == "programme":
        story.append(Paragraph("Programme schedule values above are the values submitted with this application.", styles["BodyCustom"]))
    if code == "declaration":
        story.append(Paragraph("Designated officer: Registrar. The institution accepts responsibility for the information supplied.", styles["BodyCustom"]))
    story += [Spacer(1, 9 * mm), Paragraph(
        "Institution-prepared supporting record. Referenced approvals, certifications and issuing authorities require independent confirmation.",
        styles["FootCustom"])]
    SimpleDocTemplate(str(path), pagesize=A4, rightMargin=21 * mm, leftMargin=21 * mm,
                      topMargin=20 * mm, bottomMargin=20 * mm).build(story)


def build(root: Path = ROOT) -> tuple[int, int]:
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing package: {root}")
    root.mkdir(parents=True, exist_ok=True)
    applications = documents = 0
    for inst in INSTITUTIONS:
        college = root / safe_name(inst["name"])
        college.mkdir()
        (college / "institution.txt").write_text("\n".join([
            f"Institution name: {inst['name']}",
            f"Institution reference: {inst['ref']}", f"Existing approval reference: {inst['approval']}",
            f"Address: {inst['address']}", f"District: {inst['district']}", f"State: {inst['state']}",
            f"Affiliation: {inst['affiliation']}", f"Faculty entries: {inst['faculty']}",
            f"Rooms and facilities: {inst['rooms']}", "", "Use the existing portal account password.",
            "The institution owns these supporting records; external-source confirmation is a separate review step.", "",
        ]), encoding="utf-8")
        for index, category in enumerate(CATEGORIES, 1):
            form = fields_for(inst, category)
            app_dir = college / f"{index:02d} - {safe_name(category['name'])}"
            app_dir.mkdir()
            checklist = requirements(category["id"])
            lines = [f"APPLICATION: {category['name']}", f"CATEGORY ID: {category['id']}",
                     f"INSTITUTION: {inst['name']}", "", "FORM INPUTS"]
            lines.extend(f"{key}: {value}" for key, value in form.items())
            lines += ["declaration: Yes", "", "UPLOAD EACH FILE WITH THIS DOCUMENT TYPE"]
            for req in checklist:
                code = req["code"]
                filename = f"{code}.pdf"
                reference = f"{inst['ref']}-{category['id'].upper()}-{code.upper()}"
                make_pdf(app_dir / filename, inst, category, form, code, reference)
                lines.append(f"{code}: {filename} ({req['flag']})")
                documents += 1
            lines += ["", "SEQUENCE", "1. Open this application category in the institution portal.",
                      "2. Enter all form inputs and upload every listed PDF under its document type.",
                      "3. Confirm the declaration and select Save and submit application.",
                      "4. Review delivery, extraction, evidence and officer status in VerifyFlow.", ""]
            (app_dir / "input.txt").write_text("\n".join(lines), encoding="utf-8")
            applications += 1
    (root / "README.txt").write_text(
        "Institution application input packages\n\n"
        "Three existing portal accounts are covered. Each college folder has one institution.txt and "
        "twelve application folders. Each application folder has input.txt and every checklist PDF.\n"
        "The PDFs are institution-prepared records for workflow testing, not letters or certificates issued by a regulator.\n"
        "Use only authorized issuer sources for authenticity checks. A matching hash or unsigned PDF does not establish origin.\n",
        encoding="utf-8")
    return applications, documents


if __name__ == "__main__":
    count, files = build()
    print(f"Prepared {count} applications and {files} PDFs in {ROOT}")
