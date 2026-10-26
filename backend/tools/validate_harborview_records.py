"""Check every Harborview PDF's text, extracted identity and local signature trust."""

from pathlib import Path

import pymupdf

from app.extraction.definitions import load_definitions
from app.extraction.ocr import UnavailableOcrEngine
from app.extraction.pipeline import run
from app.trust.anchors import load
from app.trust.signatures import Options, inspect

ROOT = Path(r"E:\sih 2\mock-aicte-portal\institution_packages\Harborview Institute of Engineering")
TRUST = Path(r"E:\sih 2\backend\var\institution-trust")
NAME = "Harborview Institute of Engineering"
REFERENCE = "HIE-REG-001"


def main() -> None:
    definitions, _ = load_definitions()
    material = load(TRUST / "roots", TRUST / "crls")
    if material.problems:
        raise AssertionError(material.problems)
    failures = []
    files = sorted(ROOT.rglob("*.pdf"))
    values_by_application: dict[Path, dict[str, set[str]]] = {}
    for path in files:
        data = path.read_bytes()
        extracted = run(data, "application/pdf", path.stem, definitions, UnavailableOcrEngine(), 0)
        fields = {field.definition.key: field for field in extracted.fields}
        values = values_by_application.setdefault(path.parent, {})
        for key, field in fields.items():
            if field.normalized_value:
                values.setdefault(key, set()).add(field.normalized_value)
        for key, expected in (("institution_name", NAME), ("institution_reference", REFERENCE)):
            found = fields.get(key)
            if not found or found.normalized_value != expected or found.alternatives:
                failures.append((str(path), key, found.normalized_value if found else None))
        checks, _ = inspect(data, "application/pdf", Options(material))
        if any(check.state.value != "verified" for check in checks) or len(checks) != 4:
            failures.append((str(path), "trust", [(c.dimension.value, c.state.value, c.code) for c in checks]))
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            text = "\n".join(page.get_text() for page in doc).lower()
        if any(word in text for word in ("synthetic", "mock", "demo", "fictional")):
            failures.append((str(path), "wording", "unexpected marker"))
    for folder, fields in values_by_application.items():
        for key, distinct in fields.items():
            if len(distinct) > 1:
                failures.append((str(folder), key, sorted(distinct)))
    print(f"PDFs={len(files)}; signature/trust checks={len(files) * 4}; failures={len(failures)}")
    if failures:
        for problem in failures[:10]:
            print(problem)
        raise AssertionError("Harborview package validation failed")


if __name__ == "__main__":
    main()
