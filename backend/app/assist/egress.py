"""Egress control: what document content may leave this environment, and how it is framed when it does.

The policy (``VERIFYFLOW_AI_DOCUMENT_EGRESS``) is a ceiling, checked per task:

- ``none``: only rule and finding metadata (rule names, outcomes, reason codes, field labels, page numbers).
  No extracted values, no page text, no file names (documents are referred to as "Document 1", "Document 2").
- ``extracted_values``: also extracted and corrected field values, identifier values masked unless configured
  otherwise, and correction reasons.
- ``page_text``: also page text, which document classification and field suggestions need.

Everything taken from a document or a stored record is wrapped in an element the system prompt declares to be
data, never instructions, and any copy of those delimiters inside the content is neutralized so a document can't
close the element and speak as the operator. A manifest of what was sent is stored with every interaction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

POLICY_RANK = {"none": 0, "extracted_values": 1, "page_text": 2}
MASKED_TYPES = {"identifier", "document_number"}

DATA_TAGS = ("untrusted_document_text", "record")
_TAG_RE = re.compile(r"<\s*/?\s*(?:" + "|".join(DATA_TAGS) + r")\b[^>]*>", re.IGNORECASE)


def allows(policy: str, needed: str) -> bool:
    return POLICY_RANK.get(policy, 0) >= POLICY_RANK[needed]


def mask(value: str) -> str:
    """Keep the last 4 characters of an identifier so a reviewer can still tell values apart."""
    v = value.strip()
    if len(v) <= 4:
        return "•" * len(v)
    return "•" * (len(v) - 4) + v[-4:]


def neutralize(text: str) -> str:
    """Remove any copy of the data delimiters from content, so it can't break out of its element."""
    return _TAG_RE.sub("[tag removed]", text)


def attr(value: str) -> str:
    return neutralize(value).replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


def body(value: str) -> str:
    return neutralize(value).replace("<", "&lt;").replace(">", "&gt;")


# Heuristic signals of text addressed to an AI model. They are *reported* to the reviewer, not relied on: the
# defence is structural (data framing, no tools, strict output schemas, server-side validation of every value
# and reference). A document that triggers one is still processed.
_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ignore_instructions", re.compile(r"\b(ignore|disregard|forget)\b.{0,40}\b(instruction|prompt|rule|above)s?\b", re.I | re.S)),
    ("role_override", re.compile(r"\b(you are now|act as|pretend to be|new instructions|developer mode|jailbreak)\b", re.I)),
    ("system_prompt", re.compile(r"\b(system|operator)\s*(prompt|message|instruction)s?\b", re.I)),
    ("secret_request", re.compile(r"\b(api[\s_-]?key|password|secret|credential|token)s?\b", re.I)),
    ("tool_request", re.compile(r"\b(call|invoke|run|execute)\b.{0,30}\b(tool|function|command|code)\b", re.I | re.S)),
    ("verdict_injection", re.compile(r"\b(mark|set|report|treat)\b.{0,40}\b(as\s+)?(authentic|verified|approved|pass(ed)?|genuine)\b", re.I | re.S)),
    ("chat_markup", re.compile(r"(^|\n)\s*(assistant|system|human|user)\s*:", re.I)),
]


def injection_signals(text: str) -> list[str]:
    return [name for name, pattern in _INJECTION_PATTERNS if pattern.search(text)]


@dataclass
class Manifest:
    """What left the environment for one request. Stored with the interaction and shown to the reviewer."""

    policy: str
    categories: set[str] = field(default_factory=set)
    documents: list[str] = field(default_factory=list)  # document ids whose content was included
    pages: list[dict] = field(default_factory=list)  # [{document_id, page_number, chars}]
    masked_values: int = 0
    withheld: list[str] = field(default_factory=list)  # categories the policy kept back
    truncated: bool = False
    chars_sent: int = 0
    injection_signals: list[dict] = field(default_factory=list)  # [{where, signals}]

    def note_signals(self, where: str, text: str) -> None:
        found = injection_signals(text)
        if found:
            self.injection_signals.append({"where": where, "signals": found})

    def as_dict(self) -> dict:
        return {
            "policy": self.policy,
            "categories": sorted(self.categories),
            "documents": self.documents,
            "pages": self.pages,
            "masked_values": self.masked_values,
            "withheld": sorted(set(self.withheld)),
            "truncated": self.truncated,
            "chars_sent": self.chars_sent,
            "injection_signals": self.injection_signals,
        }


def wrap_page(document_label: str, page_number: int, text: str) -> str:
    return (
        f'<untrusted_document_text document="{attr(document_label)}" page="{page_number}">\n'
        f"{body(text)}\n</untrusted_document_text>"
    )


def pages_within(pages: list[tuple[int, str]], limit: int) -> tuple[list[tuple[int, str]], bool]:
    """Whole pages in order until the character limit; a page that doesn't fit is cut and nothing after it is sent."""
    out: list[tuple[int, str]] = []
    used = 0
    for number, text in pages:
        if used + len(text) <= limit:
            out.append((number, text))
            used += len(text)
            continue
        room = limit - used
        if room > 200:
            out.append((number, text[:room]))
        return out, True
    return out, False
