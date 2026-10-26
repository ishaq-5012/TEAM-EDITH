"""Deterministic fictional institutional universe and controlled scenarios."""

import random
from datetime import date, timedelta

SCENARIOS = ("complete", "missing_evidence", "inconsistent_evidence")
FIRST = ("Aster", "Cedar", "Meridian", "Bluehaven", "Northstar", "Silverleaf", "Maple", "Larkspur", "Orion", "Harbor", "Elm", "Juniper", "Willow", "Summit")
SECOND = ("Grove", "Field", "Vale", "Brook", "Crest", "Ridge", "Hollow", "Meadow", "Point", "Garden", "Arc", "Glade", "Mosaic", "Horizon")
DISTRICTS = ("Fictional North", "Demonstration East", "Model Central", "Sample Coast", "Test Valley", "Imaginary West")
COURSES = ("Computer Engineering", "Civil Engineering", "Electrical Engineering", "Mechanical Engineering", "Applied Electronics", "Data Science")
DEPARTMENTS = ("Computing", "Civil Systems", "Electrical Systems", "Mechanical Systems", "Applied Electronics", "Data Sciences")
OWNERS = ("Fictional Educational Trust", "Demo Learning Society", "Model Academic Foundation")


def make_institution(index: int, seed: int):
    rng = random.Random(seed * 100003 + index * 7919)
    name = f"{FIRST[index % len(FIRST)]} {SECOND[(index * 5 + seed) % len(SECOND)]} Institute of Technology"
    iid = f"INST-DEMO-{seed:04d}-{index + 1:03d}"
    campus = f"CMP-DEMO-{seed:04d}-{index + 1:03d}"
    programmes = []
    chosen = rng.sample(range(len(COURSES)), 3)
    for j, course_idx in enumerate(chosen):
        programmes.append(dict(id=f"PRG-{index + 1:03d}-{j + 1:02d}",
                               name=COURSES[course_idx], department=DEPARTMENTS[course_idx],
                               level="Undergraduate", approved_intake=60 + 30 * rng.randint(0, 2),
                               divisions=1 + rng.randint(0, 1)))
    faculty = []
    for p in programmes:
        for k in range(8 + rng.randint(0, 3)):
            n = len(faculty) + 1
            faculty.append(dict(id=f"FAC-{index + 1:03d}-{n:03d}", name=f"Faculty Demo {index + 1:03d}-{n:02d}",
                                department=p["department"], programme_id=p["id"],
                                qualification="PhD (synthetic)" if k % 4 == 0 else "M.Tech (synthetic)",
                                designation="Professor" if k == 0 else "Assistant Professor",
                                appointment_year=2026 if index < 3 else 2017 + (k + index) % 8))
    rooms = []
    for p in programmes:
        for k in range(4):
            rooms.append(dict(id=f"RM-{index + 1:03d}-{len(rooms) + 1:03d}", campus_id=campus,
                              department=p["department"], type="Teaching laboratory" if k < 2 else "Classroom",
                              area_sqm=85 + 10 * k + rng.randint(0, 20),
                              equipment_units=20 + 5 * k if k < 2 else 0))
    rooms.extend([dict(id=f"RM-{index + 1:03d}-{len(rooms) + k + 1:03d}", campus_id=campus,
                       department="Shared", type=t, area_sqm=area, equipment_units=0)
                  for k, (t, area) in enumerate((("Library", 310), ("Seminar hall", 180), ("Accessible services", 90)))])
    is_new = index < 3
    established = 2026 if is_new else 2002 + (index * 3 + seed) % 18
    return dict(id=iid, name=name, short_name=f"{FIRST[index % 14]} {SECOND[(index * 5 + seed) % 14]}",
                logo_file=f"institutions/logos/{iid}.svg", ownership=OWNERS[index % 3],
                institution_type="Private non-profit (fictional)",
                address=f"Plot {100 + index}, Demo Campus Avenue, {DISTRICTS[index % len(DISTRICTS)]}, Demo Pradesh 000000",
                district=DISTRICTS[index % len(DISTRICTS)], state="Demo Pradesh (fictional)",
                campus_id=campus, established_year=established,
                management=f"{FIRST[index % 14]} {OWNERS[index % 3]}",
                contact_email=f"institution-{index + 1:03d}@example.invalid",
                affiliation="Demonstration Technical Board (fictional)",
                programmes=programmes, faculty=faculty, rooms=rooms,
                library=dict(print_titles=3000 + index * 37, ebooks=900 + index * 19,
                             journal_subscriptions=22 + index % 9, reading_seats=100 + index % 40),
                finance=dict(annual_income_lakh=720 + index * 11,
                             annual_expenditure_lakh=650 + index * 9,
                             laboratory_allocation_lakh=85 + index * 2),
                history=([dict(reference=f"HIST-DEMO-{seed:04d}-{index + 1:03d}-01",
                               year=2026, event="Fictional governing sponsor formed a new-institution proposal"),
                          dict(reference=f"HIST-DEMO-{seed:04d}-{index + 1:03d}-02",
                               year=2026, event="Synthetic planned programme and campus inventory prepared")]
                         if is_new else
                         [dict(reference=f"HIST-DEMO-{seed:04d}-{index + 1:03d}-01",
                               year=2024, event="Fictional institutional record — no official approval asserted"),
                          dict(reference=f"HIST-DEMO-{seed:04d}-{index + 1:03d}-02",
                               year=2025, event="Synthetic programme inventory update")]))


def make_application(category, institution, scenario, index, seed, as_of):
    aid = f"VF-DEMO-{as_of.year}-{index + 1:06d}"
    base = institution["programmes"][0]
    before = base["approved_intake"]
    family = category["family"]
    after = before
    if family == "new":
        before = 0
    elif family in ("intake", "division", "restoration"):
        after = before + (30 if category["id"] != "intake-reduction" else -30)
    elif family == "supernumerary":
        after = before + 12
    elif family == "closure":
        after = 0
    proposed_name = institution["name"]
    if family == "name":
        proposed_name = institution["name"].replace("Institute of Technology", "College of Applied Technology")
    proposal = {
        "target_programme_id": base["id"], "target_programme": base["name"],
        "before_intake": before, "after_intake": after,
        "proposed_institution_name": proposed_name,
        "proposed_site": f"Plot {900 + index}, New Demo Campus Road, {institution['district']}, Demo Pradesh 000000"
        if family == "site" else institution["address"],
        "proposed_affiliation": "Model Technical University (fictional)" if family == "affiliation" else institution["affiliation"],
        "additional_course": "Sustainable Computing (fictional proposal)" if family == "course" else None,
        "new_level": "Postgraduate (fictional proposal)" if family == "level" else None,
        "partner_institution": f"Partner Demo College {index + 1:03d} (fictional)" if family == "merger" else None,
    }
    issued = as_of - timedelta(days=7 + index % 12)
    return dict(id=aid, institution_id=institution["id"], category_id=category["id"],
                category_name=category["name"], scenario=scenario, submitted_date=as_of.isoformat(),
                document_date=issued.isoformat(), rule_version="AICTE APH 2024-2027 (category reference); DEMO-1 document templates",
                missing_field="management_contact" if scenario == "missing_evidence" else None,
                management_contact=None if scenario == "missing_evidence" else f"Demo Office {index + 1:03d}",
                proposal=proposal)


def logo_svg(institution):
    initials = "".join(word[0] for word in institution["short_name"].split()[:2])
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="180" height="180" viewBox="0 0 180 180">
<rect width="180" height="180" rx="32" fill="#17243c"/><path d="M22 126 L90 30 L158 126" fill="none" stroke="#5dc9c1" stroke-width="12"/>
<circle cx="90" cy="88" r="37" fill="#4353a3"/><text x="90" y="101" text-anchor="middle" font-family="Arial" font-size="34" font-weight="bold" fill="white">{initials}</text>
<text x="90" y="158" text-anchor="middle" font-family="Arial" font-size="11" fill="#b9d5e8">DEMO MARK</text></svg>'''
