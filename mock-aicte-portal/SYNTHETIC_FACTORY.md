# Synthetic application document factory

This independent factory creates fictional AICTE-style application packages for local VerifyFlow AI demonstrations. It writes only under `synthetic_data/runs/<run-name>` by default. It does not connect to AICTE, the sibling VerifyFlow backend/frontend, or this portal's SQLite database and uploads. The output is ignored by Git.

## Source and rule status

The [AICTE Approval Process Handbook 2024–2027](https://aicte-qa.aicte-india.org/sites/default/files/APH%20Final.pdf) was checked on 2026-10-25. Chapter I and Chapter II identify the 14 application types in the catalogue; Annexure 2 clause 2.6(iii) refers to a management resolution for additional courses/divisions. Those two requirement mappings are marked `conditional_official_reference`. Their generated PDFs are plainly synthetic unsigned stand-ins. All other 229 document requirements are `demo_only`, including the form, schedules, checklist and case-specific records. No later amendment or 2026–27 availability determination was verified. Catalogue entries retain source URL, edition, clause where verified, review date and verification status. The existence of a category in a handbook does not imply eligibility for this or any other cycle.

The generator deliberately produces no government certificate, real approval letter, notarized affidavit, real signature, seal or verification link. Every PDF page carries `SYNTHETIC — DEMO ONLY — NOT AN OFFICIAL DOCUMENT`.

## PowerShell setup and commands

From `E:\sih 2\mock-aicte-portal`:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt -r requirements-factory.txt

# All 14 categories, three cases each, fixed seed and date
python -m synthetic_factory generate --all --institutions-per-category 3 --seed 42 --as-of 2026-10-25 --run seed-42
python -m synthetic_factory validate --run seed-42
python -m synthetic_factory report --run seed-42
python -m synthetic_factory list --run seed-42

# One fictional institution shown across all 14 categories as alternative examples
python -m synthetic_factory generate --all --case complete --shared-institution --seed 42 --run one-institution-42
python -m synthetic_factory validate --run one-institution-42
python -m synthetic_factory inputs --run one-institution-42

# One category, all three scenarios
python -m synthetic_factory generate --category extension-of-approval --seed 42 --run eoa-42

# One specific application package
python -m synthetic_factory generate --category new-course --case inconsistent_evidence --seed 42 --run course-review-42

# Regenerate the same marked run; the same seed/date/configuration reproduces file contents
python -m synthetic_factory generate --all --seed 42 --as-of 2026-10-25 --run seed-42 --replace-generated-run

# Independent alternative dataset
python -m synthetic_factory generate --all --seed 314 --as-of 2026-10-25 --run seed-314

# Remove only one marked factory run
python -m synthetic_factory clean --run seed-314

# Tests
python -m unittest discover -s tests -p 'test_synthetic_factory.py' -v
```

`--replace-generated-run` and `clean` require a factory marker and a run name confined to `synthetic_data/runs`. Output roots inside `var/`, `../backend/` or `../frontend/` are rejected. Existing files are never silently overwritten. The normal portal commands and records remain independent.

## Output and interface

`synthetic_data/runs/seed-42/` contains:

- `catalogue/`: category, document requirement and source records.
- `institutions/`: complete fictional registry and original logo SVGs.
- `applications/<category>/<application-id>/`: PDF documents, JSON and CSV data, scenario manifest.
- `reports/`: generation totals, coverage by category, PDF inventory and package validation results.
- `reports/input_guide.md` and `input_inventory.csv`: text values to enter and exact local PDF paths for each application.

Each package manifest records the generation parameters, document references, SHA-256 hashes, requirement mappings, omitted evidence, intended discrepancies and validation outcome. JSON/CSV paths and application references form a future export/import interface; no import into an application database is performed. A consumer should copy selected files using its own authenticated demo-import workflow and retain the manifest alongside them.

The `--shared-institution` mode reuses the same fictional identity and programme/facility records across categories for an input demonstration. Treat its applications as **alternative scenarios**, not as simultaneous submissions or one real approval chronology. It does not add these applications to the portal database.

Scenario `complete` contains all applicable demo requirements. `missing_evidence` omits the library statement and management contact, recorded in its checklist and manifest. `inconsistent_evidence` changes the target intake only in the programme PDF; the registry, CSV and expected-discrepancy manifest retain the original value. The validator reports this as an expected demo inconsistency, while unexpected hash, mapping, completeness, date, PDF, CSV or identity errors fail validation.
