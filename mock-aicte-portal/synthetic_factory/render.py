"""Document-specific ReportLab templates with a visible status on every page."""

from collections import Counter
from html import escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, LongTable, TableStyle, KeepTogether

from .catalogue import CATEGORIES, DOC_TITLES

STATUS = "SYNTHETIC — DEMO ONLY — NOT AN OFFICIAL DOCUMENT"
NAVY = colors.HexColor("#18263d")
TEAL = colors.HexColor("#007f84")
PALE = colors.HexColor("#edf4f7")
INK = colors.HexColor("#263747")

styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="DocTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=17,
                          leading=21, textColor=NAVY, spaceAfter=10, alignment=TA_LEFT))
styles.add(ParagraphStyle(name="SectionSynthetic", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=10.5,
                          leading=14, textColor=TEAL, spaceBefore=12, spaceAfter=6))
styles.add(ParagraphStyle(name="BodySynthetic", parent=styles["BodyText"], fontName="Helvetica", fontSize=9,
                          leading=13, textColor=INK, spaceAfter=5))
styles.add(ParagraphStyle(name="SmallSynthetic", parent=styles["BodyText"], fontName="Helvetica", fontSize=7.5,
                          leading=10, textColor=INK))
styles.add(ParagraphStyle(name="TableHeadSynthetic", parent=styles["BodyText"], fontName="Helvetica-Bold", fontSize=7.5,
                          leading=9.5, textColor=colors.white))


def para(value, style="BodySynthetic"):
    return Paragraph(escape(str(value)).replace("\n", "<br/>"), styles[style])


def section(title, number):
    return para(f"{number}. {title}", "SectionSynthetic")


def table(headers, rows, widths=None):
    data = [[para(h, "TableHeadSynthetic") for h in headers]]
    data += [[para(v, "SmallSynthetic") for v in row] for row in rows]
    t = LongTable(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, TEAL),
    ]))
    return t


def facts(items):
    return table(["Field", "Synthetic value"], [[k, v] for k, v in items], [48 * mm, 135 * mm])


def programme_rows(inst):
    return [[p["id"], p["name"], p["department"], p["level"], p["approved_intake"], p["divisions"]]
            for p in inst["programmes"]]


def change_facts(app, inst):
    q = app["proposal"]
    return [
        ("Target programme", f"{q['target_programme']} ({q['target_programme_id']})"),
        ("Existing approved intake", q["before_intake"]),
        ("Proposed intake", q["after_intake"]),
        ("Existing name", inst["name"]),
        ("Proposed name", q["proposed_institution_name"]),
        ("Existing site", inst["address"]),
        ("Proposed site", q["proposed_site"]),
        ("Existing affiliation", inst["affiliation"]),
        ("Proposed affiliation", q["proposed_affiliation"]),
    ]


def body_for(doc_type, app, inst, doc_ref, requirements, included, missing, conflict):
    story = []
    q = app["proposal"]
    title = DOC_TITLES[doc_type]
    story += [para(title, "DocTitle"),
              para("Generated for a fictional institution. Figures, identities, references, dates and statements are for demonstration and extraction testing only."),
              facts([("Document reference", doc_ref), ("Application reference", app["id"]),
                     ("Institution reference", inst["id"]), ("Institution name", inst["name"]),
                     ("Application category", app["category_name"]), ("Scenario", app["scenario"].replace("_", " ").title()),
                     ("Document date", app["document_date"]), ("Rule mapping", app["rule_version"])]),
              Spacer(1, 5 * mm)]

    if doc_type == "application_form":
        story += [section("Applicant and management", 1),
                  facts([("Institution", inst["name"]), ("Ownership", inst["ownership"]),
                         ("Address", inst["address"]), ("Management", inst["management"]),
                         ("Management contact", app["management_contact"] or "MISSING — DEMO EVIDENCE GAP"),
                         ("Contact", inst["contact_email"])]),
                  section("Application proposal", 2), facts(change_facts(app, inst)),
                  section("Submission statement", 3),
                  para("This form records a synthetic scenario. It is not an AICTE application or approval request.")]
    elif doc_type == "application_summary":
        story += [section("Requested action", 1), para(f"The fictional applicant seeks a demonstration review for: {app['category_name']}."),
                  section("Before and after", 2), facts(change_facts(app, inst)[:3]),
                  section("Readiness", 3),
                  para("One item is intentionally incomplete in this test case." if app["scenario"] == "missing_evidence"
                       else "A documented demo inconsistency requires review." if conflict else "All required demonstration evidence is present.")]
    elif doc_type == "institution_profile":
        story += [section("Identity", 1), facts([("Institution", inst["name"]), ("Established", inst["established_year"]),
                  ("Institution type", inst["institution_type"]), ("Management", inst["management"]),
                  ("District and state", f"{inst['district']}, {inst['state']}"), ("Campus", inst["campus_id"]),
                  ("Affiliation", inst["affiliation"])]), section("Academic and facility totals", 2),
                  facts([("Proposed programmes" if app["category_id"] == "new-institution" else "Existing programmes", len(inst["programmes"])),
                         ("Total planned intake" if app["category_id"] == "new-institution" else "Total approved intake", sum(p["approved_intake"] for p in inst["programmes"])),
                         ("Faculty roster", len(inst["faculty"])), ("Rooms and facilities", len(inst["rooms"]))])]
    elif doc_type == "document_checklist":
        rows = []
        for req in requirements:
            d = req["document_type"]
            decision = "MISSING — DEMO GAP" if d in missing else "INCLUDED" if d in included else "NOT APPLICABLE"
            rows.append([req["id"], req["description"], req["requirement_level"], req["classification"], decision])
        story += [section("Package evidence", 1),
                  para("The matrix distinguishes official category references from demo document templates. Included means generated in this package, not official compliance."),
                  table(["Requirement", "Document", "Level", "Class", "Status"], rows,
                        [39 * mm, 58 * mm, 21 * mm, 29 * mm, 36 * mm]),
                  section("Source and rule mapping", 2),
                  para(f"Application category reference: AICTE Approval Process Handbook 2024-2027, {next(c[2] for c in CATEGORIES if c[0] == app['category_id'])}."),
                  para("DEMO-1 identifies the synthetic document templates. The catalogue JSON records each requirement's classification, edition, reviewed date and source URL."),
                  *[para(f"{r['id']}: {r['source_clause']} — generated as an unsigned demo stand-in.") for r in requirements if r["source_clause"]],
                  section("Outstanding items", 3),
                  para(", ".join(missing) if missing else "None in this synthetic scenario."),
                  para("The management-contact field is also intentionally blank." if app["missing_field"] else "All demonstration form fields are populated.")]
    elif doc_type == "programme_schedule":
        rows = programme_rows(inst)
        if conflict:
            rows[0][4] += 30
        story += [section("Proposed programme plan" if app["category_id"] == "new-institution" else "Existing programme register", 1),
                  table(["Programme ID", "Programme", "Department", "Level", "Planned intake" if app["category_id"] == "new-institution" else "Intake", "Divisions"], rows,
                        [27 * mm, 49 * mm, 43 * mm, 27 * mm, 18 * mm, 19 * mm]),
                  section("Summary", 2),
                  facts([("Programme count", len(rows)), ("Total listed intake", sum(r[4] for r in rows)),
                         ("Target programme", q["target_programme"])]),
                  para("Programme register reflects an intentional demo discrepancy requiring review." if conflict else
                       "Programme plan matches the fictional applicant registry." if app["category_id"] == "new-institution" else
                       "Programme register matches the fictional institution registry.")]
    elif doc_type == "faculty_master":
        story += [section("Faculty master register", 1),
                  table(["Faculty ID", "Synthetic name", "Department", "Programme", "Qualification", "Joined"],
                        [[f["id"], f["name"], f["department"], f["programme_id"], f["qualification"], f["appointment_year"]]
                         for f in inst["faculty"]], [27 * mm, 43 * mm, 43 * mm, 25 * mm, 30 * mm, 15 * mm]),
                  section("Control totals", 2), facts([("Faculty entries", len(inst["faculty"])),
                                                       ("Departments", len(set(f["department"] for f in inst["faculty"])))])]
    elif doc_type == "staffing_summary":
        counts = Counter(f["department"] for f in inst["faculty"])
        story += [section("Department-wise staffing", 1),
                  table(["Department", "Programme reference", "Faculty", "PhD / Fellow (demo)"],
                        [[p["department"], p["id"], counts[p["department"]],
                          sum(f["qualification"].startswith("PhD") for f in inst["faculty"] if f["department"] == p["department"])]
                         for p in inst["programmes"]], [58 * mm, 46 * mm, 34 * mm, 45 * mm]),
                  section("Staffing control", 2), facts([("Total faculty", sum(counts.values())),
                                                         ("Roster reference", "faculty_master.pdf")])]
    elif doc_type == "infrastructure_inventory":
        story += [section("Campus inventory", 1),
                  table(["Room ID", "Campus ID", "Department", "Room type", "Area sq m", "Equipment"],
                        [[r["id"], r["campus_id"], r["department"], r["type"], r["area_sqm"], r["equipment_units"]]
                         for r in inst["rooms"]], [29 * mm, 31 * mm, 40 * mm, 44 * mm, 19 * mm, 20 * mm]),
                  section("Facility totals", 2), facts([("Campus", inst["campus_id"]),
                   ("Rooms", len(inst["rooms"])), ("Teaching laboratories", sum(r["type"] == "Teaching laboratory" for r in inst["rooms"])),
                   ("Listed equipment units", sum(r["equipment_units"] for r in inst["rooms"]))])]
    elif doc_type == "library_resources":
        story += [section("Learning resources", 1), facts([("Print titles", inst["library"]["print_titles"]),
                  ("E-books", inst["library"]["ebooks"]), ("Journal subscriptions", inst["library"]["journal_subscriptions"]),
                  ("Reading seats", inst["library"]["reading_seats"]), ("Library room", next(r["id"] for r in inst["rooms"] if r["type"] == "Library"))]),
                  section("Access arrangements", 2), para("A synthetic discovery catalogue, reading room and digital resource terminals serve the listed programmes.")]
    elif doc_type == "financial_summary":
        f = inst["finance"]
        story += [section("Unaudited demonstration values", 1),
                  table(["Measure", "INR lakh (synthetic)", "Basis"],
                        [["Projected annual income" if app["category_id"] == "new-institution" else "Annual income", f["annual_income_lakh"], "Demo plan" if app["category_id"] == "new-institution" else "Demo ledger"],
                         ["Projected annual expenditure" if app["category_id"] == "new-institution" else "Annual expenditure", f["annual_expenditure_lakh"], "Demo plan" if app["category_id"] == "new-institution" else "Demo ledger"],
                         ["Laboratory allocation", f["laboratory_allocation_lakh"], "Included in expenditure"],
                         ["Illustrative surplus", f["annual_income_lakh"] - f["annual_expenditure_lakh"], "Calculated"]],
                        [72 * mm, 50 * mm, 61 * mm]), section("Status", 2),
                  para("This schedule is fictional and unaudited. It is not a certified account or financial statement.")]
    elif doc_type == "application_history":
        story += [section("Fictional history", 1), table(["Reference", "Year", "Event"],
                  [[h["reference"], h["year"], h["event"]] for h in inst["history"]], [57 * mm, 23 * mm, 103 * mm]),
                  section("Current event", 2), facts([("Current application", app["id"]), ("Submission date", app["submitted_date"])])]
    elif doc_type == "declaration":
        story += [section("Demonstration declaration", 1),
                  para(f"The fictional management of {inst['name']} records the data in this package for a controlled demonstration of document intake and review."),
                  para("No regulatory filing, approval, certification, affidavit, audited record, or legal attestation is created by this document."),
                  section("Signatory field", 2), facts([("Signature", "Synthetic signatory placeholder — no real signature"),
                                                       ("Mark", "DEMO MARK — NOT OFFICIAL"), ("Prepared", app["document_date"])])]
    else:
        story += category_body(doc_type, app, inst)
    return story


def category_body(doc_type, app, inst):
    q = app["proposal"]
    target_department = next(p["department"] for p in inst["programmes"] if p["id"] == q["target_programme_id"])
    target_faculty = [f for f in inst["faculty"] if f["programme_id"] == q["target_programme_id"]]
    target_labs = [r for r in inst["rooms"] if r["department"] == target_department and r["type"] == "Teaching laboratory"]
    items = [section("Category-specific record", 1)]
    if doc_type in {"intake_comparison", "division_proposal", "supernumerary_proposal"}:
        items += [table(["Programme", "Current intake", "Proposed intake", "Delta"],
                        [[q["target_programme"], q["before_intake"], q["after_intake"], q["after_intake"] - q["before_intake"]]],
                        [69 * mm, 38 * mm, 38 * mm, 38 * mm]),
                  para("Proposed values are application scenario data; existing register values remain separately identified.")]
    elif doc_type in {"site_change_proposal", "campus_facilities", "safety_demo_record"}:
        items += [facts([("Current campus", inst["campus_id"]), ("Current address", inst["address"]),
                         ("Proposed address", q["proposed_site"]), ("Inventory rooms", len(inst["rooms"]))]),
                  table(["Facility class", "Rooms", "Total floor area sq m"],
                        [[kind, sum(r["type"] == kind for r in inst["rooms"]),
                          sum(r["area_sqm"] for r in inst["rooms"] if r["type"] == kind)]
                         for kind in ("Teaching laboratory", "Classroom", "Library", "Seminar hall", "Accessible services")],
                        [75 * mm, 40 * mm, 68 * mm]),
                  para("This is a fictional facility/evidence record. It is not a building plan, fire clearance, or authority-issued certificate.")]
    elif doc_type in {"name_change_comparison", "affiliation_change_record"}:
        items += [facts([("Existing institution name", inst["name"]), ("Proposed institution name", q["proposed_institution_name"]),
                         ("Existing affiliation", inst["affiliation"]), ("Proposed affiliation", q["proposed_affiliation"])]),
                  para("Names and affiliating bodies in this record are fictional and carry no external recognition.")]
    elif doc_type == "merger_comparison":
        items += [facts([("Illustrative parent", inst["name"]), ("Illustrative partner", q["partner_institution"]),
                         ("Parent programmes", len(inst["programmes"])), ("Parent campus", inst["campus_id"])]),
                  table(["Record", "Parent side", "Partner side"],
                        [["Identity", inst["id"], "Partner identity pending (demo)"],
                         ["Programmes", len(inst["programmes"]), "Not supplied in test scenario"],
                         ["Learner continuity", "Existing teaching plans retained", "Requires separate review"]],
                        [45 * mm, 69 * mm, 69 * mm]),
                  para("Partner facts are scenario placeholders; this is not a real institutional merger.")]
    elif doc_type in {"new_course_proposal", "new_level_proposal", "new_institution_proposal"}:
        items += [facts([("Proposed programme" if doc_type == "new_institution_proposal" else "Existing target", q["target_programme"]),
                         ("Additional course", q["additional_course"] or "Not applicable"),
                         ("New level", q["new_level"] or "Not applicable"), ("Prepared for", inst["name"])]),
                  table(["Academic planning measure", "Synthetic value", "Linked evidence"],
                        [["Target department", target_department, "Programme schedule"],
                         ["Faculty available", len(target_faculty), "Faculty master"],
                         ["Teaching laboratories", len(target_labs), "Infrastructure inventory"],
                         ["Planned intake", q["after_intake"], "Application form"]],
                        [62 * mm, 52 * mm, 69 * mm]),
                  para("Academic objectives, staffing and facilities are illustrated by the linked schedules in this package.")]
    elif doc_type in {"course_closure_plan", "student_continuity"}:
        items += [facts([("Affected course", q["target_programme"]), ("Current intake", q["before_intake"]),
                         ("Proposed future intake", q["after_intake"]), ("Continuity contact", "Demo Student Office")]),
                  table(["Stage", "Demonstration action", "Evidence owner"],
                        [["2026-27", "Cease new admissions to affected course", "Demo Academic Office"],
                         ["2027-28", "Continue teaching for existing fictional cohorts", target_department],
                         ["2028-29", "Close remaining teaching and archive records", "Demo Student Office"]],
                        [32 * mm, 105 * mm, 46 * mm]),
                  para("Existing learners in this fictional example retain access to scheduled instruction, faculty and library resources through the illustration period.")]
    elif doc_type == "restoration_timeline":
        items += [table(["Year", "Synthetic event", "Reference"],
                        [[h["year"], h["event"], h["reference"]] for h in inst["history"]] +
                        [[2025, f"Illustrative intake gap for {q['target_programme']}", "GAP-DEMO-2025"]] +
                        [[app["submitted_date"], "Demo intake restoration request", app["id"]]],
                        [30 * mm, 93 * mm, 60 * mm]),
                  facts([("Illustrative prior intake", q["after_intake"]),
                         ("Current scenario intake", q["before_intake"]),
                         ("Requested restoration", q["after_intake"])])]
    elif doc_type == "governing_body":
        items += [facts([("Governing entity", inst["management"]), ("Ownership", inst["ownership"]),
                         ("Recorded contact", app["management_contact"] or "MISSING — DEMO EVIDENCE GAP")]),
                  table(["Illustrative role", "Function", "Identity status"],
                        [["Chair", "Academic oversight", "Role placeholder"],
                         ["Secretary", "Record custody", "Role placeholder"],
                         ["Finance member", "Budget monitoring", "Role placeholder"]],
                        [42 * mm, 79 * mm, 62 * mm]),
                  para("No real trustees, directors or signatures are represented.")]
    elif doc_type == "management_resolution":
        items += [facts([("Illustrative resolution", f"RES-DEMO-{app['id']}"), ("Applicant", inst["management"]),
                         ("Proposed action", app["category_name"]), ("Prepared", app["document_date"])]),
                  table(["Agenda", "Recorded demo decision"],
                        [["Academic action", app["category_name"]],
                         ["Resource plan", f"{len(target_faculty)} mapped faculty and {len(target_labs)} teaching labs reviewed"],
                         ["Intake plan", f"{q['before_intake']} to {q['after_intake']} seats in target programme"]],
                        [48 * mm, 135 * mm]),
                  para("Synthetic management resolution template — not signed, notarised, submitted or valid as official evidence."),
                  para("Synthetic signatory placeholder — no real signature")]
    elif doc_type == "computer_network":
        items += [facts([("Campus", inst["campus_id"]), ("Lab workstations", sum(r["equipment_units"] for r in inst["rooms"] if r["type"] == "Teaching laboratory")),
                         ("Synthetic network", "Campus demo LAN; no public endpoint")])]
    elif doc_type == "student_services":
        items += [facts([("Reading seats", inst["library"]["reading_seats"]), ("Accessibility room", next(r["id"] for r in inst["rooms"] if r["type"] == "Accessible services")),
                         ("Support desk", "Fictional Student Services")])]
    elif doc_type == "continuation_review":
        items += [facts([("Programmes reviewed", len(inst["programmes"])),
                         ("Existing intake", sum(p["approved_intake"] for p in inst["programmes"])),
                         ("Faculty roster count", len(inst["faculty"])),
                         ("Campus inventory rooms", len(inst["rooms"]))]),
                  table(["Review area", "Demo evidence", "Status"],
                        [["Academic offer", "Programme schedule", "Available"],
                         ["Staffing", "Faculty master and staffing summary", "Available"],
                         ["Physical resources", "Infrastructure and library statements", "Available"]],
                        [50 * mm, 95 * mm, 38 * mm])]
    elif doc_type == "change_justification":
        items += [facts(change_facts(app, inst)[:3]),
                  para(f"The fictional institution proposes {app['category_name'].lower()} for the target programme {q['target_programme']}. The before-and-after figures above are the scenario's controlled comparison."),
                  table(["Review consideration", "Synthetic basis"],
                        [["Academic capacity", f"{len(target_faculty)} faculty mapped to the target programme"],
                         ["Practical facilities", f"{len(target_labs)} teaching laboratories in {target_department}"],
                         ["Resource continuity", f"{inst['library']['print_titles']} print titles in the campus library"]],
                        [62 * mm, 121 * mm])]
    else:
        items += [facts(change_facts(app, inst)[:3]),
                  para(f"This {app['category_name'].lower()} record links the proposed action to {q['target_programme']}, the faculty mapping and the fictional campus inventory."),
                  facts([("Target department", target_department), ("Mapped faculty", len(target_faculty)),
                         ("Teaching laboratories", len(target_labs)), ("Campus reference", inst["campus_id"])])]
    items += [section("Evidence links within this package", 2),
              para("See the application form, programme schedule, faculty roster, infrastructure inventory and checklist for linked synthetic records."),
              section("Preparation status", 3),
              para("For controlled demonstration use only. No official verification or decision is implied.")]
    return items


def render_pdf(path: Path, doc_type: str, app: dict, inst: dict, requirement: dict,
               requirements: list, included: set, missing: set, conflict: bool):
    path.parent.mkdir(parents=True, exist_ok=True)
    doc_ref = f"DOC-{app['id']}-{doc_type.upper().replace('_', '-') }"
    def decorate(canvas, document):
        canvas.saveState()
        w, h = A4
        canvas.setFillColor(NAVY)
        canvas.rect(0, h - 24 * mm, w, 24 * mm, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawString(14 * mm, h - 10 * mm, "FICTIONAL INSTITUTION DOCUMENT FACTORY")
        canvas.setFont("Helvetica-Bold", 8.5)
        canvas.drawString(14 * mm, h - 17 * mm, STATUS)
        # Original abstract mark, matching the fictional SVG identity system.
        canvas.setStrokeColor(colors.HexColor("#5dc9c1"))
        canvas.setLineWidth(1.5)
        canvas.line(w - 28 * mm, h - 18 * mm, w - 21 * mm, h - 7 * mm)
        canvas.line(w - 21 * mm, h - 7 * mm, w - 14 * mm, h - 18 * mm)
        canvas.setFillColor(colors.HexColor("#4353a3"))
        canvas.circle(w - 21 * mm, h - 13 * mm, 2.4 * mm, fill=1, stroke=0)
        canvas.setFillColor(TEAL)
        canvas.rect(0, 0, w, 13 * mm, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(14 * mm, 6 * mm, f"{app['id']}  |  {inst['id']}  |  {doc_type}")
        canvas.drawRightString(w - 14 * mm, 6 * mm, f"Page {document.page}")
        canvas.restoreState()
    pdf = SimpleDocTemplate(str(path), pagesize=A4, rightMargin=14 * mm, leftMargin=14 * mm,
                            topMargin=29 * mm, bottomMargin=18 * mm, title=DOC_TITLES[doc_type],
                            author="Synthetic Document Factory", subject=STATUS, pageCompression=1, invariant=1)
    body = body_for(doc_type, app, inst, doc_ref, requirements, included, missing, conflict)
    pdf.build(body, onFirstPage=decorate, onLaterPages=decorate)
    return doc_ref
