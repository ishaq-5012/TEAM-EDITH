"""Behavioural checks for the isolated synthetic document factory."""

import tempfile
import unittest
from pathlib import Path

from pypdf import PdfReader

from synthetic_factory.catalogue import category_records, requirement_records
from synthetic_factory.factory import clean, generate, read_json, safe_run, sha256, validate
from synthetic_factory.render import render_pdf
from synthetic_factory.universe import SCENARIOS, make_institution


class FactoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name) / "generated"
        cls.run_dir = generate(cls.root, "test-42", 42, ["new-institution"], list(SCENARIOS))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_catalogue_and_three_cases(self):
        self.assertGreaterEqual(len(category_records()), 14)
        manifests = [read_json(p) for p in self.run_dir.glob("applications/*/*/scenario_manifest.json")]
        self.assertEqual({m["scenario_type"] for m in manifests}, set(SCENARIOS))
        self.assertEqual(len({m["institution_id"] for m in manifests}), 3)
        self.assertEqual(len({m["application_id"] for m in manifests}), 3)
        self.assertTrue(all(m["rule_version"] for m in manifests))
        self.assertTrue(all(r["verification_status"] in {"verified", "demo_only"} for r in requirement_records()))

    def test_reproducibility_and_uniqueness(self):
        self.assertEqual(make_institution(0, 42), make_institution(0, 42))
        self.assertNotEqual(make_institution(0, 42), make_institution(0, 43))
        refs = [f["document_reference"] for p in self.run_dir.glob("applications/*/*/scenario_manifest.json")
                for f in read_json(p)["document_inventory"] if f["format"] == "pdf"]
        self.assertEqual(len(refs), len(set(refs)))
        package = next(self.run_dir.glob("applications/*/*/scenario_manifest.json")).parent
        data = read_json(package / "structured_data.json")
        app, inst = data["application"], data["institution"]
        requirements = [r for r in requirement_records() if r["category_id"] == app["category_id"]]
        requirement = next(r for r in requirements if r["document_type"] == "application_summary")
        one = Path(self.temp.name) / "repro-one.pdf"
        two = Path(self.temp.name) / "repro-two.pdf"
        for path in (one, two):
            render_pdf(path, "application_summary", app, inst, requirement, requirements,
                       {r["document_type"] for r in requirements}, set(), False)
        self.assertEqual(sha256(one), sha256(two))

    def test_documents_and_expected_scenarios(self):
        result = validate(self.run_dir, save=False)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["expected_demo_inconsistencies"], 1)
        for p in self.run_dir.glob("applications/*/*/scenario_manifest.json"):
            m = read_json(p)
            for f in m["document_inventory"]:
                path = self.run_dir / f["path"]
                self.assertTrue(path.is_file())
                self.assertGreater(path.stat().st_size, 0)
                if f["format"] == "pdf":
                    pages = PdfReader(str(path)).pages
                    self.assertGreater(len(pages), 0)
                    self.assertIn("SYNTHETIC", pages[0].extract_text())

    def test_unexpected_defect_detected(self):
        pdf = next(self.run_dir.glob("applications/*/*/application_summary.pdf"))
        original = pdf.read_bytes()
        try:
            pdf.write_bytes(original + b"tampered")
            result = validate(self.run_dir, save=False)
            self.assertGreater(result["failed"], 0)
            self.assertTrue(any("HASH_OR_SIZE_MISMATCH" in error for case in result["results"]
                                for error in case["unexpected_errors"]))
        finally:
            pdf.write_bytes(original)

    def test_output_safety_and_no_overwrite(self):
        with self.assertRaises(ValueError):
            safe_run(Path(__file__).resolve().parents[1] / "var" / "uploads", "bad")
        with self.assertRaises(ValueError):
            safe_run(self.root, "../escape")
        with self.assertRaises(FileExistsError):
            generate(self.root, "test-42", 42, ["new-institution"], ["complete"])
        sentinel = Path(self.temp.name) / "existing_upload.txt"
        sentinel.write_text("user record", encoding="utf-8")
        other = self.root / "runs" / "unmarked"
        other.mkdir()
        with self.assertRaises(ValueError):
            clean(self.root, "unmarked")
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "user record")

    def test_shared_institution_input_guide(self):
        run = generate(self.root, "shared-two", seed=42,
                       category=["new-institution", "extension-of-approval"],
                       cases=["complete"], shared_institution=True)
        registry = read_json(run / "institutions" / "institution_registry.json")
        self.assertEqual(len(registry), 1)
        manifests = [read_json(p) for p in run.glob("applications/*/*/scenario_manifest.json")]
        self.assertEqual(len(manifests), 2)
        self.assertEqual({m["institution_id"] for m in manifests}, {registry[0]["id"]})
        contacts = {read_json(p.parent / "structured_data.json")["application"]["management_contact"]
                    for p in run.glob("applications/*/*/scenario_manifest.json")}
        self.assertEqual(contacts, {"Demo Office 001"})
        guide = (run / "reports" / "input_guide.md").read_text(encoding="utf-8")
        self.assertIn("Text / number / date inputs", guide)
        self.assertIn("Document inputs and exact stored locations", guide)
        self.assertIn("application_form.pdf", guide)
        self.assertEqual(validate(run, save=False)["failed"], 0)


if __name__ == "__main__":
    unittest.main()
