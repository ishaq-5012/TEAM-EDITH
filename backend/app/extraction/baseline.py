"""Deterministic baseline extractor ("label: value" rules).

WHAT IT DOES
  For each configured field it looks for a line that starts with one of the field's labels, followed by
  ":" or a dash, and takes the rest of that line as the value. Addresses may continue onto the following
  lines of the same text block (up to ``max_lines``). The value's bounding box is the union of the words
  that make up the value.

WHAT IT DOES NOT DO (stated in the API and UI)
  It does not understand layouts, tables, forms without labels, values on a different line from their label
  (except addresses), handwriting, or arbitrary documents. A value it doesn't find is reported as "missing";
  it never guesses. It was designed and is tested on synthetic fixtures that follow the "Label: value"
  convention. Real-world coverage requires a stronger extractor (for example an AI provider), which plugs in
  through the same interface and must still return values grounded in page text and coordinates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.extraction.definitions import FieldDefinition, FieldDefinitionSet, FieldType, PORTAL_DOCUMENT_TYPES
from app.extraction.normalizers import normalize
from app.extraction.pages import LOW_CONFIDENCE, PageContent, Word
from app.models.extraction import FieldStatus, TextSource

EXTRACTOR = "baseline-rules"
VERSION = "1.0"
LIMITATIONS = (
    "Rule-based baseline: finds a value only where a configured label is followed by ':' or '-' on the same line "
    "(addresses may continue onto following lines). It does not understand layouts, tables, unlabeled values or "
    "handwriting, and was validated only on synthetic documents. Missing values are reported, never guessed."
)
_SEP = r"\s*[:：\-–—]\s*"


@dataclass
class Line:
    page: PageContent
    words: list[Word]
    text: str
    spans: list[tuple[int, int]]  # character span of each word within text


@dataclass
class FieldResult:
    definition: FieldDefinition
    status: str
    raw_value: str | None = None
    normalized_value: str | None = None
    normalized_data: dict | None = None
    note: str | None = None
    method: str | None = None
    matched_label: str | None = None
    page_number: int | None = None
    bbox: list[float] | None = None
    confidence: float | None = None
    flags: list[str] = field(default_factory=list)
    alternatives: list[dict] = field(default_factory=list)


def build_lines(page: PageContent) -> list[Line]:
    grouped: dict[str, list[Word]] = {}
    for w in page.words:
        grouped.setdefault(w.line_key, []).append(w)
    lines = []
    for words in grouped.values():
        parts, spans, pos = [], [], 0
        for w in words:
            if parts:
                pos += 1
            spans.append((pos, pos + len(w.text)))
            parts.append(w.text)
            pos += len(w.text)
        lines.append(Line(page, words, " ".join(parts), spans))
    return lines


def _words_in(line: Line, start: int, end: int) -> list[Word]:
    return [w for w, (a, b) in zip(line.words, line.spans, strict=True) if a < end and b > start]


def _reading_box(w: Word, page: PageContent) -> tuple[float, float, float, float]:
    """Map a displayed-space box back to the page's reading orientation (inverse of PyMuPDF's rotation_matrix).

    Used only for layout reasoning ("is this line directly below that one?"); stored coordinates stay displayed.
    """
    W, H = page.width, page.height  # displayed size  # noqa: N806
    r = page.rotation % 360
    if r == 90:
        return w.y0, W - w.x1, w.y1, W - w.x0
    if r == 180:
        return W - w.x1, H - w.y1, W - w.x0, H - w.y0
    if r == 270:
        return H - w.y1, w.x0, H - w.y0, w.x1
    return w.x0, w.y0, w.x1, w.y1


def _union(words: list[Word]) -> list[float]:
    return [
        round(min(w.x0 for w in words), 2),
        round(min(w.y0 for w in words), 2),
        round(max(w.x1 for w in words), 2),
        round(max(w.y1 for w in words), 2),
    ]


def _label_regex(definition: FieldDefinition) -> re.Pattern[str]:
    labels = sorted(definition.labels, key=len, reverse=True)  # longest first: "Date of birth" before "Date"
    alternation = "|".join(re.escape(label).replace(r"\ ", r"\s+") for label in labels)
    return re.compile(rf"^\s*(?P<label>{alternation}){_SEP}(?P<value>.*?)\s*$", re.IGNORECASE)


def _starts_with_any_label(text: str, all_labels: re.Pattern[str]) -> bool:
    return bool(all_labels.match(text))


@dataclass
class _Candidate:
    raw: str
    words: list[Word]
    page: PageContent
    label: str


def _find(definition: FieldDefinition, lines: list[Line], any_label: re.Pattern[str]) -> list[_Candidate]:
    pattern = _label_regex(definition)
    out: list[_Candidate] = []
    for i, line in enumerate(lines):
        m = pattern.match(line.text)
        if not m:
            continue
        value_words = _words_in(line, m.start("value"), m.end("value")) if m["value"] else []
        raw_parts = [m["value"]] if m["value"] else []
        if definition.type == FieldType.ADDRESS:
            limit = (definition.max_lines or 4) - len(raw_parts)
            # Continuation lines are found by geometry, not block numbers (which vary by PDF producer and OCR):
            # directly below the previous line and left-aligned with the value or the label.
            page = line.page

            def box(w: Word, page: PageContent = page) -> tuple[float, float, float, float]:
                return _reading_box(w, page)

            anchors = [box(line.words[0])[0]] + ([box(value_words[0])[0]] if value_words else [])
            prev = line
            j = i + 1
            while limit > 0 and j < len(lines):
                nxt = lines[j]
                prev_boxes, next_boxes = [box(w) for w in prev.words], [box(w) for w in nxt.words]
                height = max(b[3] for b in prev_boxes) - min(b[1] for b in prev_boxes)
                gap = min(b[1] for b in next_boxes) - max(b[3] for b in prev_boxes)
                aligned = any(abs(next_boxes[0][0] - a) <= max(4.0, 0.75 * height) for a in anchors)
                if (
                    nxt.page is not line.page
                    or not nxt.text.strip()
                    or not (-0.25 * height <= gap <= 1.0 * height)
                    or not aligned
                    or _starts_with_any_label(nxt.text, any_label)
                ):
                    break
                raw_parts.append(nxt.text)
                value_words.extend(nxt.words)
                prev = nxt
                limit -= 1
                j += 1
        if raw_parts and value_words:
            out.append(_Candidate("\n".join(raw_parts), value_words, line.page, m["label"]))
    return out


def _find_portal_table(definition: FieldDefinition, lines: list[Line]) -> list[_Candidate]:
    """Read synthetic portal PDFs whose field and value occupy adjacent table cells."""
    labels = {" ".join(label.casefold().split()) for label in definition.labels}
    out: list[_Candidate] = []
    for line in lines:
        if " ".join(line.text.casefold().split()) not in labels or not line.words:
            continue
        label_box = _reading_box(line.words[0], line.page)
        candidates = []
        for other in lines:
            if other is line or other.page is not line.page or not other.words:
                continue
            value_box = _reading_box(other.words[0], other.page)
            if value_box[0] <= max(_reading_box(word, line.page)[2] for word in line.words) + 8:
                continue
            if abs(value_box[1] - label_box[1]) > 3:
                continue
            candidates.append((value_box[0], other))
        if candidates:
            _, value = min(candidates, key=lambda pair: pair[0])
            out.append(_Candidate(value.text, value.words, line.page, line.text))
    return out


def _find_portal_inline_intake(lines: list[Line]) -> list[_Candidate]:
    out: list[_Candidate] = []
    pattern = re.compile(r";\s*intake\s*:\s*(?P<value>[0-9]{1,6})\.?\s*$", re.I)
    for line in lines:
        match = pattern.search(line.text)
        if match:
            words = _words_in(line, match.start("value"), match.end("value"))
            if words:
                out.append(_Candidate(match["value"], words, line.page, "intake"))
    return out


def extract(pages: list[PageContent], definitions: FieldDefinitionSet, document_type: str | None) -> list[FieldResult]:
    lines = [ln for page in pages for ln in build_lines(page)]
    every_label = sorted({label for d in definitions.fields for label in d.labels}, key=len, reverse=True)
    all_labels = re.compile(
        r"^\s*(?:" + "|".join(re.escape(label).replace(r"\ ", r"\s+") for label in every_label) + ")" + _SEP,
        re.IGNORECASE,
    )
    unreadable_pages = [p.page_number for p in pages if p.text_source == TextSource.NONE.value]
    results: list[FieldResult] = []
    for definition in definitions.fields:
        if not definition.applies_to(document_type):
            continue
        candidates = _find(definition, lines, all_labels)
        if definition.scope == "portal" and document_type in PORTAL_DOCUMENT_TYPES:
            candidates = _find_portal_table(definition, lines) + candidates
            if definition.key == "current_intake":
                candidates.extend(_find_portal_inline_intake(lines))
        # A precise label takes precedence over a shorter alias. For example,
        # "Institution name:" must beat a footer beginning "Institution-prepared".
        # Keep all occurrences of the preferred label so real conflicts remain visible.
        if candidates:
            longest = max(len(candidate.label.strip()) for candidate in candidates)
            candidates = [candidate for candidate in candidates if len(candidate.label.strip()) == longest]
        if not candidates:
            r = FieldResult(definition, FieldStatus.MISSING.value)
            if unreadable_pages:
                r.flags.append("pages_without_text")
                pages_list = ", ".join(map(str, unreadable_pages))
                r.note = f"Not found. Page(s) {pages_list} had no readable text, so the value may be there."
            if document_type and document_type in definition.required_for:
                r.flags.append("required_missing")
            results.append(r)
            continue

        first = candidates[0]
        from_ocr = first.page.text_source == TextSource.OCR.value
        norm = normalize(first.raw, definition, from_ocr)
        r = FieldResult(
            definition,
            norm.status,
            raw_value=first.raw,
            normalized_value=norm.value,
            normalized_data=norm.data,
            note=norm.note,
            method="ocr_rule" if from_ocr else "text_layer_rule",
            matched_label=first.label,
            page_number=first.page.page_number,
            bbox=_union(first.words),
            flags=list(norm.flags),
        )
        confidence = 0.9
        if from_ocr:
            r.flags.append("ocr_source")
            word_conf = [w.confidence for w in first.words if w.confidence is not None]
            mean = sum(word_conf) / len(word_conf) if word_conf else 0.0
            confidence = min(confidence, mean / 100)
            if mean < LOW_CONFIDENCE:
                r.flags.append("low_ocr_confidence")
        if norm.status == "invalid":
            confidence *= 0.5
        elif norm.status == "ambiguous":
            confidence *= 0.7
        r.confidence = round(confidence, 3)

        # Other occurrences: identical values are fine, different ones are surfaced, never silently dropped.
        for other in candidates[1:]:
            other_norm = normalize(other.raw, definition, other.page.text_source == TextSource.OCR.value)
            if (other_norm.value or other.raw) != (norm.value or first.raw):
                r.alternatives.append(
                    {
                        "raw_value": other.raw,
                        "normalized_value": other_norm.value,
                        "page_number": other.page.page_number,
                        "bbox": _union(other.words),
                    }
                )
        if r.alternatives:
            r.flags.append("conflicting_candidates")
        results.append(r)
    return results
