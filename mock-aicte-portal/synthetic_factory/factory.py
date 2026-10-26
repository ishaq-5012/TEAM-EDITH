"""Generation, reporting and independent output validation."""

import csv
import hashlib
import json
import shutil
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from pypdf import PdfReader

from . import VERSION
from .catalogue import (CATEGORIES, DOC_TITLES, REVIEWED, RULE_VERSION,
                        category_records, requirement_records, source_records)
from .render import STATUS, render_pdf
from .universe import SCENARIOS, logo_svg, make_application, make_institution

DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "synthetic_data"
MARKER = ".synthetic_factory_run.json"


def dump_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_csv(path, headers, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        writer.writerows(rows)


def safe_run(root: Path, run_name: str):
    if not run_name or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in run_name):
        raise ValueError("Run name may contain only letters, numbers, hyphens and underscores")
    root = root.resolve()
    portal = Path(__file__).resolve().parents[1]
    forbidden = [portal / "var", portal.parent / "backend", portal.parent / "frontend"]
    if any(root == p.resolve() or root.is_relative_to(p.resolve()) for p in forbidden):
        raise ValueError("Output root overlaps portal user data or the sibling VerifyFlow project")
    target = (root / "runs" / run_name).resolve()
    if target.parent != (root / "runs").resolve():
        raise ValueError("Run path escapes the generated-output directory")
    return target


def clean(root: Path, run_name: str):
    target = safe_run(root, run_name)
    if not target.exists():
        return False
    marker = target / MARKER
    if not marker.is_file() or read_json(marker).get("factory") != "synthetic_factory":
        raise ValueError("Refusing to remove an unmarked directory")
    shutil.rmtree(target)
    return True


def selected_categories(category):
    records = category_records()
    if not category or category == "all":
        return records
    wanted = set(category)
    found = [r for r in records if r["id"] in wanted]
    absent = wanted - {r["id"] for r in found}
    if absent:
        raise ValueError(f"Unknown category: {', '.join(sorted(absent))}")
    return found


def is_applicable(requirement, family):
    doc = requirement["document_type"]
    return (doc != "safety_demo_record" or family == "site") and (doc != "student_services" or family == "supernumerary")


def generate(root=DEFAULT_ROOT, run_name="seed-42", seed=42, category=None,
             cases=None, as_of="2026-10-25", replace=False, shared_institution=False):
    root = Path(root).resolve()
    target = safe_run(root, run_name)
    chosen = selected_categories(category)
    cases = cases or list(SCENARIOS)
    if any(case not in SCENARIOS for case in cases):
        raise ValueError("Unknown scenario")
    as_of_date = date.fromisoformat(as_of)
    if target.exists():
        if not replace:
            raise FileExistsError(f"{target} exists. Use --replace-generated-run to regenerate this marked run.")
        clean(root, run_name)
    target.mkdir(parents=True)
    dump_json(target / MARKER, dict(factory="synthetic_factory", version=VERSION, seed=seed,
                                   run_name=run_name, as_of=as_of,
                                   shared_institution=shared_institution))
    catalogue_dir = target / "catalogue"
    categories = category_records()
    requirements = requirement_records()
    sources = source_records()
    dump_json(catalogue_dir / "application_categories.json", categories)
    dump_json(catalogue_dir / "document_requirements.json", requirements)
    dump_json(catalogue_dir / "source_references.json", sources)
    req_by_cat = defaultdict(list)
    for r in requirements:
        req_by_cat[r["category_id"]].append(r)
    inst_registry = []
    package_paths = []
    inventory = []
    package_summaries = []
    for category_record in chosen:
        cat_idx = next(i for i, item in enumerate(categories) if item["id"] == category_record["id"])
        for case_idx, scenario in enumerate(cases):
            global_idx = cat_idx * 3 + SCENARIOS.index(scenario)
            inst = make_institution(0 if shared_institution else global_idx, seed)
            app = make_application(category_record, inst, scenario, global_idx, seed, as_of_date)
            if shared_institution and app["management_contact"] is not None:
                app["management_contact"] = "Demo Office 001"
            if not any(existing["id"] == inst["id"] for existing in inst_registry):
                inst_registry.append(inst)
            logo = target / inst["logo_file"]
            logo.parent.mkdir(parents=True, exist_ok=True)
            logo.write_text(logo_svg(inst), encoding="utf-8")
            package = target / "applications" / category_record["id"] / app["id"]
            package.mkdir(parents=True, exist_ok=True)
            package_paths.append(package)
            applicable = req_by_cat[category_record["id"]]
            missing = {"library_resources"} if scenario == "missing_evidence" else set()
            included = {r["document_type"] for r in applicable if is_applicable(r, category_record["family"])} - missing
            files = []
            for r in applicable:
                doc_type = r["document_type"]
                if doc_type not in included:
                    continue
                out = package / (doc_type + ".pdf")
                ref = render_pdf(out, doc_type, app, inst, r, applicable, included, missing,
                                 scenario == "inconsistent_evidence" and doc_type == "programme_schedule")
                item = dict(path=out.relative_to(target).as_posix(), sha256=sha256(out),
                            bytes=out.stat().st_size, document_type=doc_type,
                            document_reference=ref, requirement_id=r["id"],
                            requirement_classification=r["classification"], source_id=r["source_id"],
                            source_clause=r["source_clause"], format="pdf")
                files.append(item)
                inventory.append(dict(application_id=app["id"], institution_id=inst["id"],
                                      category_id=app["category_id"], scenario=scenario, **item))
            structured = package / "structured_data.json"
            dump_json(structured, dict(institution=inst, application=app))
            files.append(dict(path=structured.relative_to(target).as_posix(), sha256=sha256(structured),
                              bytes=structured.stat().st_size, document_type="structured_data", format="json",
                              requirement_id=None, requirement_classification="demo_only", source_id=None))
            for name, headers, rows in [
                ("faculty_schedule.csv", ["faculty_id", "synthetic_name", "department", "programme_id", "qualification"],
                 [[f[k] for k in ("id", "name", "department", "programme_id", "qualification")] for f in inst["faculty"]]),
                ("infrastructure_schedule.csv", ["room_id", "campus_id", "department", "type", "area_sqm", "equipment_units"],
                 [[r[k] for k in ("id", "campus_id", "department", "type", "area_sqm", "equipment_units")] for r in inst["rooms"]]),
                ("programme_schedule.csv", ["programme_id", "name", "department", "approved_intake", "divisions"],
                 [[p[k] for k in ("id", "name", "department", "approved_intake", "divisions")] for p in inst["programmes"]]),
            ]:
                out = package / name
                write_csv(out, headers, rows)
                files.append(dict(path=out.relative_to(target).as_posix(), sha256=sha256(out),
                                  bytes=out.stat().st_size, document_type=name[:-4], format="csv",
                                  requirement_id=None, requirement_classification="demo_only", source_id=None))
            expected = ([dict(code="PROGRAMME_INTAKE_MISMATCH", document_type="programme_schedule",
                              field="approved_intake", programme_id=inst["programmes"][0]["id"],
                              registry_value=inst["programmes"][0]["approved_intake"],
                              document_value=inst["programmes"][0]["approved_intake"] + 30,
                              description="Deliberate demo inconsistency requiring review")]
                        if scenario == "inconsistent_evidence" else [])
            manifest = dict(application_id=app["id"], institution_id=inst["id"],
                            application_category=app["category_id"], scenario_type=scenario,
                            rule_version=RULE_VERSION, generation_timestamp=f"{as_of}T00:00:00Z",
                            generator_version=VERSION, random_seed=seed, document_inventory=files,
                            missing_evidence=[dict(document_type=d, requirement_id=next(r["id"] for r in applicable if r["document_type"] == d)) for d in sorted(missing)],
                            missing_fields=[app["missing_field"]] if app["missing_field"] else [],
                            optional_non_applicable=[dict(document_type=r["document_type"],
                                                          reason=("Optional demo evidence included" if r["requirement_level"] == "optional"
                                                                  else "Condition does not apply to this application category"))
                                                     for r in applicable if r["requirement_level"] == "optional" or
                                                     not is_applicable(r, category_record["family"])],
                            expected_scenario_inconsistencies=expected,
                            validation_results={"status": "pending; run validate command"})
            dump_json(package / "scenario_manifest.json", manifest)
            package_summaries.append(dict(application_id=app["id"], category_id=app["category_id"],
                                          scenario=scenario, institution_id=inst["id"],
                                          pdf_count=sum(f["format"] == "pdf" for f in files)))
    dump_json(target / "institutions" / "institution_registry.json", inst_registry)
    reports = target / "reports"
    reports.mkdir(exist_ok=True)
    write_csv(reports / "document_inventory.csv",
              ["application_id", "institution_id", "category_id", "scenario", "path", "sha256", "bytes", "document_type", "document_reference", "requirement_id", "requirement_classification", "source_id", "source_clause", "format"],
              [[entry.get(k, "") for k in ("application_id", "institution_id", "category_id", "scenario", "path", "sha256", "bytes", "document_type", "document_reference", "requirement_id", "requirement_classification", "source_id", "source_clause", "format")] for entry in inventory])
    report(target)
    input_guide(target)
    return target


def text_inputs(app, inst):
    """Human-facing values corresponding to a hypothetical form for this case."""
    q = app["proposal"]
    cat = app["category_id"]
    result = [
        ("Institution name", inst["name"]),
        ("Institution reference", inst["id"]),
        ("Institution address", inst["address"]),
        ("Management body", inst["management"]),
        ("Management contact", app["management_contact"] or "MISSING — DEMO GAP"),
        ("Application reference", app["id"]),
        ("Application type", app["category_name"]),
        ("Submission date", app["submitted_date"]),
        ("Academic year", f"{int(app['submitted_date'][:4]) + 1}-{str(int(app['submitted_date'][:4]) + 2)[-2:]}"),
    ]
    existing_ref = inst["history"][0]["reference"]
    if cat != "new-institution":
        result.append(("Existing fictional history reference", existing_ref))
    if cat in {"new-institution", "extension-of-approval", "intake-increase", "intake-reduction",
               "new-course", "new-level", "course-closure", "intake-restoration",
               "division-addition", "supernumerary-seats"}:
        result.append(("Programme / course", q["additional_course"] if cat == "new-course" else q["target_programme"]))
    if cat in {"new-institution", "extension-of-approval", "new-course", "new-level"}:
        result.append(("Programme level", q["new_level"] or "Undergraduate"))
    if cat in {"extension-of-approval", "intake-increase", "intake-reduction", "course-closure",
               "intake-restoration", "division-addition", "supernumerary-seats"}:
        result.append(("Current intake", q["before_intake"]))
    if cat in {"new-institution", "intake-increase", "intake-reduction", "new-course", "new-level",
               "intake-restoration", "division-addition", "supernumerary-seats"}:
        result.append(("Proposed intake", q["after_intake"]))
    if cat == "institution-name-change":
        result.append(("Proposed institution name", q["proposed_institution_name"]))
    if cat == "site-change":
        result.append(("Proposed site / location", q["proposed_site"]))
    if cat == "affiliation-change":
        result.append(("Proposed affiliation", q["proposed_affiliation"]))
    if cat == "institution-merger":
        result.append(("Illustrative merger partner", q["partner_institution"]))
    if cat == "division-addition":
        base = next(p for p in inst["programmes"] if p["id"] == q["target_programme_id"])
        result.append(("Proposed divisions", base["divisions"] + 1))
    if cat == "supernumerary-seats":
        result.append(("Illustrative supernumerary seats", q["after_intake"] - q["before_intake"]))
    if cat in {"institution-name-change", "site-change", "course-closure", "affiliation-change", "institution-merger"}:
        result.append(("Proposed effective date", app["submitted_date"]))
    result.append(("Justification / explanation",
                   f"Synthetic request for {app['category_name'].lower()} at {inst['name']}; review linked programme, faculty and campus evidence."))
    return result


def input_guide(run_dir):
    """Show exact text values and locations of every included PDF for each application."""
    run_dir = Path(run_dir).resolve()
    requirements = {r["id"]: r for r in read_json(run_dir / "catalogue" / "document_requirements.json")}
    manifests = [read_json(p) for p in (run_dir / "applications").glob("*/*/scenario_manifest.json")]
    order = {category_id: i for i, (category_id, _, _, _) in enumerate(CATEGORIES)}
    manifests.sort(key=lambda item: (order[item["application_category"]], item["application_id"]))
    lines = ["# Application input guide", "",
             "This is a synthetic form-input and document-location map. Document levels are demo requirements unless the catalogue explicitly links an official clause. All paths are local files.", ""]
    if read_json(run_dir / MARKER).get("shared_institution"):
        lines += ["The same fictional institution appears in independent alternative application scenarios. These are not simultaneous real regulatory filings or a chronological approval history.", ""]
    lines += ["## Application index", "", "| Category | Application ID | PDF documents |", "|---|---|---:|"]
    for item in manifests:
        lines.append(f"| {item['application_category']} | {item['application_id']} | {sum(f['format'] == 'pdf' for f in item['document_inventory'])} |")
    lines.append("")
    csv_rows = []
    for manifest in manifests:
        package = run_dir / "applications" / manifest["application_category"] / manifest["application_id"]
        data = read_json(package / "structured_data.json")
        app, inst = data["application"], data["institution"]
        lines += [f"## {app['category_name']} — {app['id']}", "",
                  f"Institution: **{inst['name']}** (`{inst['id']}`). Scenario: `{app['scenario']}`.", "",
                  "### Text / number / date inputs", "", "| Field | Value to enter |", "|---|---|"]
        for field, value in text_inputs(app, inst):
            safe_value = str(value).replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {field} | {safe_value} |")
            csv_rows.append([app["id"], app["category_id"], "text", field, str(value), "", ""])
        lines += ["", "### Document inputs and exact stored locations", "",
                  "| Document | Demo level | Stored PDF |", "|---|---|---|"]
        for item in manifest["document_inventory"]:
            if item["format"] != "pdf":
                continue
            requirement = requirements[item["requirement_id"]]
            path = (run_dir / item["path"]).as_posix()
            lines.append(f"| {requirement['description']} | {requirement['requirement_level']} ({requirement['classification']}) | [{item['document_type']}.pdf](<{path}>) |")
            csv_rows.append([app["id"], app["category_id"], "document", item["document_type"],
                             path, requirement["requirement_level"], requirement["classification"]])
        if manifest["missing_evidence"]:
            lines += ["", "Missing in this scenario: " + ", ".join(v["document_type"] for v in manifest["missing_evidence"]) + "."]
        lines += ["", f"[Package manifest](<{(package / 'scenario_manifest.json').as_posix()}>)", ""]
    guide = run_dir / "reports" / "input_guide.md"
    guide.write_text("\n".join(lines), encoding="utf-8")
    write_csv(run_dir / "reports" / "input_inventory.csv",
              ["application_id", "category_id", "input_kind", "field_or_document", "value_or_absolute_path", "demo_requirement_level", "classification"],
              csv_rows)
    return guide


def report(run_dir):
    run_dir = Path(run_dir).resolve()
    categories = read_json(run_dir / "catalogue" / "application_categories.json")
    requirements = read_json(run_dir / "catalogue" / "document_requirements.json")
    manifests = [read_json(p) for p in sorted((run_dir / "applications").glob("*/*/scenario_manifest.json"))]
    coverage_rows = []
    by_type = Counter()
    for category in categories:
        members = [m for m in manifests if m["application_category"] == category["id"]]
        docs = [f for m in members for f in m["document_inventory"] if f["format"] == "pdf"]
        by_type.update(f["document_type"] for f in docs)
        coverage_rows.append([category["id"], len(members), len({m["institution_id"] for m in members}),
                              len(docs), ",".join(sorted(m["scenario_type"] for m in members)),
                              len([r for r in requirements if r["category_id"] == category["id"]])])
    write_csv(run_dir / "reports" / "coverage_report.csv",
              ["category_id", "packages", "institutions", "pdf_documents", "scenarios", "catalogued_requirements"], coverage_rows)
    summary = dict(generator_version=VERSION, generated_date=read_json(run_dir / MARKER)["as_of"],
                   categories_with_packages=sum(r[1] > 0 for r in coverage_rows),
                   catalogue_categories=len(categories), institutions=len({m["institution_id"] for m in manifests}),
                   application_packages=len(manifests), pdf_documents=sum(by_type.values()),
                   documents_by_type=dict(sorted(by_type.items())),
                   documents_by_category={r[0]: r[3] for r in coverage_rows},
                   source_verified_document_requirements=sum(r["verification_status"] == "verified" for r in requirements),
                   demo_only_document_requirements=sum(r["verification_status"] == "demo_only" for r in requirements),
                   category_references_verified=len(categories),
                   source_limitations="APH 2024-2027 category references checked; later amendments and current cycle not verified. Demo documents are not official forms.")
    dump_json(run_dir / "reports" / "generation_report.json", summary)
    return summary


def validate(run_dir, save=True):
    run_dir = Path(run_dir).resolve()
    if read_json(run_dir / MARKER).get("factory") != "synthetic_factory":
        raise ValueError("Not a synthetic factory run")
    registry = {i["id"]: i for i in read_json(run_dir / "institutions" / "institution_registry.json")}
    requirements = {r["id"]: r for r in read_json(run_dir / "catalogue" / "document_requirements.json")}
    results = []
    all_doc_refs = set()
    all_app_ids = set()
    for p in sorted((run_dir / "applications").glob("*/*/scenario_manifest.json")):
        m = read_json(p)
        errors = []
        expected_found = []
        aid = m["application_id"]
        if aid in all_app_ids:
            errors.append("DUPLICATE_APPLICATION_ID")
        all_app_ids.add(aid)
        inst = registry.get(m["institution_id"])
        if inst is None:
            errors.append("UNKNOWN_INSTITUTION")
            continue
        package = p.parent
        data = read_json(package / "structured_data.json")
        app = data["application"]
        if data["institution"] != inst or app["id"] != aid or app["institution_id"] != inst["id"]:
            errors.append("STRUCTURED_DATA_MISMATCH")
        if app["document_date"] > app["submitted_date"]:
            errors.append("DOCUMENT_DATE_AFTER_SUBMISSION")
        if app["proposal"]["target_programme_id"] not in {x["id"] for x in inst["programmes"]}:
            errors.append("UNKNOWN_TARGET_PROGRAMME")
        target_programme = next((x for x in inst["programmes"] if x["id"] == app["proposal"]["target_programme_id"]), None)
        baseline = 0 if app["category_id"] == "new-institution" else target_programme["approved_intake"] if target_programme else None
        if target_programme and (app["proposal"]["target_programme"] != target_programme["name"] or
                                 app["proposal"]["before_intake"] != baseline):
            errors.append("PROPOSAL_BASELINE_MISMATCH")
        for filename, registry_rows, keys in [
            ("programme_schedule.csv", inst["programmes"], ("id", "name", "department", "approved_intake", "divisions")),
            ("faculty_schedule.csv", inst["faculty"], ("id", "name", "department", "programme_id", "qualification")),
            ("infrastructure_schedule.csv", inst["rooms"], ("id", "campus_id", "department", "type", "area_sqm", "equipment_units")),
        ]:
            try:
                with (package / filename).open(newline="", encoding="utf-8-sig") as stream:
                    csv_rows = list(csv.reader(stream))[1:]
                expected_rows = [[str(row[key]) for key in keys] for row in registry_rows]
                if csv_rows != expected_rows:
                    errors.append(f"CSV_REGISTRY_MISMATCH:{filename}")
            except (OSError, csv.Error):
                errors.append(f"CSV_UNREADABLE:{filename}")
        programme_ids = {x["id"] for x in inst["programmes"]}
        department_names = {x["department"] for x in inst["programmes"]}
        if any(f["programme_id"] not in programme_ids or f["department"] not in department_names for f in inst["faculty"]):
            errors.append("INVALID_FACULTY_MAPPING")
        if any(r["campus_id"] != inst["campus_id"] or
               (r["department"] != "Shared" and r["department"] not in department_names) for r in inst["rooms"]):
            errors.append("INVALID_ROOM_MAPPING")
        expected_missing = {v["document_type"] for v in m["missing_evidence"]}
        actual_types = {f["document_type"] for f in m["document_inventory"] if f["format"] == "pdf"}
        family = next(c[3] for c in CATEGORIES if c[0] == m["application_category"])
        all_required = {r["document_type"] for r in requirements.values() if r["category_id"] == m["application_category"]
                        and r["requirement_level"] != "optional" and is_applicable(r, family)}
        if all_required - actual_types != expected_missing:
            errors.append("REQUIRED_DOCUMENT_COVERAGE")
        if m["scenario_type"] == "missing_evidence" and (not expected_missing or not m["missing_fields"]):
            errors.append("MISSING_SCENARIO_NOT_RECORDED")
        if m["scenario_type"] != "missing_evidence" and (expected_missing or m["missing_fields"]):
            errors.append("UNEXPECTED_MISSING_EVIDENCE")
        for f in m["document_inventory"]:
            relative = Path(f["path"])
            file = (run_dir / relative).resolve()
            if not file.is_relative_to(run_dir) or not file.is_file():
                errors.append(f"MISSING_OR_UNSAFE_FILE:{f['path']}")
                continue
            if file.stat().st_size == 0 or f["sha256"] != sha256(file) or f["bytes"] != file.stat().st_size:
                errors.append(f"HASH_OR_SIZE_MISMATCH:{f['path']}")
            if f["format"] != "pdf":
                continue
            r = requirements.get(f["requirement_id"])
            if not r or r["category_id"] != m["application_category"] or r["document_type"] != f["document_type"]:
                errors.append(f"INVALID_REQUIREMENT_MAPPING:{f['path']}")
            if f["document_reference"] in all_doc_refs:
                errors.append("DUPLICATE_DOCUMENT_REFERENCE")
            all_doc_refs.add(f["document_reference"])
            try:
                pages = PdfReader(str(file)).pages
                if not pages:
                    errors.append(f"EMPTY_PDF:{f['path']}")
                elif (f["document_reference"] not in (pages[0].extract_text() or "") or
                      inst["name"] not in (pages[0].extract_text() or "")):
                    errors.append(f"PDF_DOCUMENT_REFERENCE_OR_NAME_MISSING:{f['path']}")
                for page in pages:
                    txt = page.extract_text() or ""
                    if STATUS not in txt or aid not in txt or inst["id"] not in txt:
                        errors.append(f"PDF_ID_OR_STATUS_MISSING:{f['path']}")
                        break
            except Exception as exc:
                errors.append(f"UNREADABLE_PDF:{f['path']}:{type(exc).__name__}")
        # Check the actual schedule PDF against registry and the recorded exception.
        schedule = package / "programme_schedule.pdf"
        if schedule.is_file():
            text = "\n".join(page.extract_text() or "" for page in PdfReader(str(schedule)).pages)
            base = inst["programmes"][0]
            wanted = base["approved_intake"] + (30 if m["scenario_type"] == "inconsistent_evidence" else 0)
            lines = [line.strip() for line in text.splitlines()]
            try:
                row_index = lines.index(base["id"])
                pdf_intake = int(lines[row_index + 4])
            except (ValueError, IndexError):
                pdf_intake = None
            if pdf_intake != wanted:
                errors.append("PROGRAMME_SCHEDULE_CONTENT_MISMATCH")
            if m["scenario_type"] == "inconsistent_evidence":
                declared = m["expected_scenario_inconsistencies"]
                if len(declared) == 1 and declared[0]["document_value"] == wanted and declared[0]["registry_value"] == base["approved_intake"]:
                    expected_found.append("PROGRAMME_INTAKE_MISMATCH")
                else:
                    errors.append("EXPECTED_INCONSISTENCY_NOT_DOCUMENTED")
        checklist = package / "document_checklist.pdf"
        if checklist.is_file() and expected_missing:
            checklist_text = "\n".join(page.extract_text() or "" for page in PdfReader(str(checklist)).pages)
            if "MISSING" not in checklist_text or not all(d.replace("_", " ")[:5].lower() in checklist_text.lower() for d in expected_missing):
                errors.append("CHECKLIST_OMISSION_MISMATCH")
        result = dict(application_id=aid, category_id=m["application_category"], scenario=m["scenario_type"],
                      status="pass" if not errors else "fail", unexpected_errors=errors,
                      expected_scenario_defects=expected_found,
                      pdf_documents=sum(f["format"] == "pdf" for f in m["document_inventory"]))
        results.append(result)
        if save:
            m["validation_results"] = result
            dump_json(p, m)
    summary = dict(packages_checked=len(results), pdf_documents_checked=sum(r["pdf_documents"] for r in results),
                   passed=sum(r["status"] == "pass" for r in results),
                   failed=sum(r["status"] == "fail" for r in results),
                   expected_demo_inconsistencies=sum(len(r["expected_scenario_defects"]) for r in results),
                   results=results)
    if save:
        dump_json(run_dir / "reports" / "validation_report.json", summary)
    return summary
