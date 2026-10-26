"""Add one institution-owned, internally consistent application package without altering existing folders."""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.catalog import CATEGORIES, DOC_TYPES, requirements
from tools import build_institution_packages as shared

INSTITUTION = dict(
    name="Harborview Institute of Engineering", username="harborview_office",
    ref="HIE-REG-001", approval="HIE-PRIOR-2025",
    programme="Computer Science and Engineering",
    address="74 Campus Road, Chennai, Tamil Nadu 600113", district="Chennai", state="Tamil Nadu",
    affiliation="South Coast Technical University", faculty=48, rooms=30,
)
ROOT = Path(__file__).resolve().parents[1] / "institution_packages" / INSTITUTION["name"]
shared.DATE = "2026-10-26"


def _frame(canvas, doc):
    width, height = A4
    canvas.saveState()
    canvas.setFillColor(colors.HexColor("#12263d"))
    canvas.rect(0, height - 36 * mm, width, 36 * mm, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 13)
    canvas.drawString(19 * mm, height - 17 * mm, "HARBORVIEW")
    canvas.setFont("Helvetica", 8)
    canvas.drawString(19 * mm, height - 23 * mm, "INSTITUTE OF ENGINEERING  /  REGISTRAR RECORDS")
    canvas.setStrokeColor(colors.HexColor("#1f7285"))
    canvas.setLineWidth(1.3)
    canvas.line(19 * mm, 20 * mm, width - 19 * mm, 20 * mm)
    canvas.setFillColor(colors.HexColor("#486175"))
    canvas.setFont("Helvetica", 8)
    canvas.drawString(19 * mm, 15 * mm, "Institution-prepared supporting record  |  HIE-REG-001")
    canvas.drawRightString(width - 19 * mm, 15 * mm, f"Page {doc.page}")
    canvas.restoreState()


def make_pdf(path: Path, category: dict, form: dict, code: str, reference: str) -> None:
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="RecordTitle", parent=styles["Heading1"], fontName="Helvetica-Bold",
                              fontSize=17, leading=21, textColor=colors.HexColor("#12263d"), spaceAfter=10))
    styles.add(ParagraphStyle(name="RecordBody", parent=styles["BodyText"], fontSize=9, leading=12,
                              textColor=colors.HexColor("#243c50"), spaceAfter=4))
    styles.add(ParagraphStyle(name="RecordSmall", parent=styles["BodyText"], fontSize=8, leading=11,
                              textColor=colors.HexColor("#506476"), spaceAfter=4))
    story = [Paragraph(DOC_TYPES[code], styles["RecordTitle"]),
             Paragraph("Institutional application supporting record", styles["RecordBody"]), Spacer(1, 2 * mm)]
    rows = [["RECORD CONTROL", "VALUE"],
            ["Application category", category["name"]], ["Document type", DOC_TYPES[code]],
            ["Document reference", reference], ["Record date", shared.DATE],
            ["Academic year", form.get("academic_year", shared.YEAR)]]
    table = Table(rows, colWidths=[49 * mm, 119 * mm], repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5f0f2")),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#15354b")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#c7d9df")),
    ]))
    story += [table, Spacer(1, 4 * mm), Paragraph("Verified record fields", styles["Heading2"])]
    for label, value in shared.document_facts(INSTITUTION, category, form, code, reference):
        story.append(Paragraph(f"<b>{label}:</b> {value}", styles["RecordBody"]))
    story += [Spacer(1, 3 * mm), Paragraph("Supporting context", styles["Heading2"]),
              Paragraph(shared.DETAILS[code], styles["RecordBody"]),
              Paragraph(form.get("justification", category["description"]), styles["RecordBody"])]
    if code == "faculty":
        story.append(Paragraph("Faculty entries: 48; academic departments: 5; doctoral-qualified faculty: 14.", styles["RecordBody"]))
    if code == "infrastructure":
        story.append(Paragraph("Rooms and facilities: 30; laboratories: 8; networked workstations: 144.", styles["RecordBody"]))
    story += [Spacer(1, 4 * mm), Paragraph("Record authentication", styles["Heading2"]),
              Paragraph("Prepared by the Registrar Office and digitally signed using the institution's local document-signing certificate. The PDF signature protects the bytes in this file; referenced external approvals require separate issuer confirmation.", styles["RecordSmall"]),
              Paragraph("Responsible office: Registrar Office, Harborview Institute of Engineering", styles["RecordSmall"])]
    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                      topMargin=40 * mm, bottomMargin=22 * mm).build(story, onFirstPage=_frame, onLaterPages=_frame)


def main() -> None:
    if ROOT.exists():
        raise FileExistsError(f"Refusing to overwrite {ROOT}")
    ROOT.mkdir(parents=True)
    inst = INSTITUTION
    (ROOT / "institution.txt").write_text("\n".join([
        f"Institution name: {inst['name']}", f"Institution reference: {inst['ref']}",
        f"Existing approval reference: {inst['approval']}", f"Address: {inst['address']}",
        f"District: {inst['district']}", f"State: {inst['state']}",
        f"Affiliation: {inst['affiliation']}", f"Faculty entries: {inst['faculty']}",
        f"Rooms and facilities: {inst['rooms']}", "",
        "The accompanying documents are institution-prepared records. External approval and issuer references require independent confirmation.",
    ]), encoding="utf-8")
    count = 0
    for index, category in enumerate(CATEGORIES, 1):
        form = shared.fields_for(inst, category)
        folder = ROOT / f"{index:02d} - {shared.safe_name(category['name'])}"
        folder.mkdir()
        lines = [f"APPLICATION: {category['name']}", f"CATEGORY ID: {category['id']}",
                 f"INSTITUTION: {inst['name']}", "", "FORM INPUTS"]
        lines.extend(f"{key}: {value}" for key, value in form.items())
        lines += ["declaration: Yes", "", "UPLOAD EACH FILE WITH THIS DOCUMENT TYPE"]
        for req in requirements(category["id"]):
            code = req["code"]
            reference = f"{inst['ref']}-{category['id'].upper()}-{code.upper()}"
            make_pdf(folder / f"{code}.pdf", category, form, code, reference)
            lines.append(f"{code}: {code}.pdf ({req['flag']})")
            count += 1
        lines += ["", "SEQUENCE", "1. Sign in to the institution portal.",
                  "2. Select this category and enter the form inputs above.",
                  "3. Upload each PDF under its matching document type.",
                  "4. Confirm the declaration and select Save and submit application.",
                  "5. Review document extraction, evidence, rules and officer status in VerifyFlow."]
        (folder / "input.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Prepared {len(CATEGORIES)} applications and {count} PDFs in {ROOT}")


if __name__ == "__main__":
    main()
