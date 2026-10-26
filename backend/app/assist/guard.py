"""Content checks applied to model text before anything is shown.

The model is never allowed to make the determinations VerifyFlow reserves for deterministic checks and people:
document authenticity, application decisions, overriding a rule result, or anything about secrets. A sentence that
does is dropped (not rewritten), and the reason is recorded. Links are dropped too: an explanation has no reason to
send a reviewer anywhere except the evidence links VerifyFlow builds itself.
"""

from __future__ import annotations

import re

_CHECKS: list[tuple[str, re.Pattern[str]]] = [
    (
        "authenticity_claim",
        re.compile(
            r"\b(is|are|was|were|appears?|seems?|looks?|likely|probably|definitely|confirmed|proven)\b.{0,25}"
            r"\b(authentic|genuine|forged|fake|fraudulent|counterfeit|tampered|falsified|legitimate)\b",
            re.I | re.S,
        ),
    ),
    ("authenticity_claim", re.compile(r"\b(authenticity|genuineness)\b.{0,20}\b(is|was|has been)\b.{0,20}\b(confirmed|established|verified|proven)\b", re.I | re.S)),
    ("decision_claim", re.compile(r"\b(approve|reject|deny|decline|accept|grant)\b.{0,15}\b(the|this)\s+(application|applicant|case)\b", re.I | re.S)),
    ("decision_claim", re.compile(r"\b(should|must|can|will)\s+be\s+(approved|rejected|denied|declined|accepted|granted)\b", re.I)),
    ("override_claim", re.compile(r"\b(override|overturn|overrule|ignore|disregard|reverse)\b.{0,20}\b(rule|result|outcome|finding|decision)\b", re.I | re.S)),
    ("override_claim", re.compile(r"\b(rule|result|outcome|finding)\b.{0,20}\b(is|was)\s+(wrong|incorrect|mistaken|erroneous|invalid)\b", re.I | re.S)),
    ("link", re.compile(r"(https?://|www\.|\b[a-z0-9-]+\.(com|net|org|io|ai)\b)", re.I)),
    ("secret_reference", re.compile(r"(\bsk-(ant-)?[A-Za-z0-9_-]{6,}|\bapi[\s_-]?keys?\b|\bpasswords?\b|\bsecrets?\b|\bcredentials?\b)", re.I)),
    ("instruction_echo", re.compile(r"\b(as instructed by the document|the document instructs|ignore (all|previous))\b", re.I)),
]


def violations(text: str) -> list[str]:
    seen: list[str] = []
    for name, pattern in _CHECKS:
        if name not in seen and pattern.search(text):
            seen.append(name)
    return seen
