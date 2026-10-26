"""Structured logging with request-ID correlation and sensitive-data redaction.

Every record passes through ``RedactionFilter`` before any handler formats it, so
passwords, tokens, secrets and Authorization headers never reach log output even
if a developer accidentally logs a request body or settings object.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

REDACTED = "[REDACTED]"

_SENSITIVE_KEY = re.compile(
    r"(pass(word|wd|phrase)?|secret|token|authorization|api[_-]?key|cookie|session|credential|private[_-]?key)",
    re.IGNORECASE,
)

# Patterns applied to free text (formatted messages, exception text).
_TEXT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Authorization: Bearer xxx / Basic xxx
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9\-._~+/]+=*"), r"\1 " + REDACTED),
    # JSON / dict style: "password": "value"  or 'token': 'value'
    (
        re.compile(
            r"""(?i)(["']?[\w-]*(?:pass(?:word|wd)?|secret|token|api[_-]?key|authorization)[\w-]*["']?\s*[:=]\s*)(["'])(.*?)\2"""
        ),
        r"\1\2" + REDACTED + r"\2",
    ),
    # key=value in query strings / env dumps: password=abc&
    (
        re.compile(r"(?i)\b([\w-]*(?:pass(?:word|wd)?|secret|token|api[_-]?key)[\w-]*=)([^\s&\"',;]+)"),
        r"\1" + REDACTED,
    ),
    # Bare JWTs
    (re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b"), REDACTED),
    # AI provider API keys (Anthropic "sk-ant-…" and generic "sk-…" style), even without a key name nearby
    (re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{16,}"), REDACTED),
    # Groq API keys ("gsk_…")
    (re.compile(r"\bgsk_[A-Za-z0-9]{20,}"), REDACTED),
    # x-api-key: value (raw HTTP header dumps)
    # (a printf placeholder such as %s is left alone: the argument it formats is redacted separately)
    (re.compile(r"(?i)\b(x-api-key\s*[:=]\s*)(?!%[-+ #0-9.]*[sdrifx]\b)\S+"), r"\1" + REDACTED),
]

# Keys whose values are document content or model text. Logged only as their size, never verbatim.
_CONTENT_KEY = re.compile(r"^(prompt|system_prompt|user_content|document_text|page_text|model_output|completion)$")


def redact_text(text: str) -> str:
    for pattern, repl in _TEXT_PATTERNS:
        text = pattern.sub(repl, text)
    return text


def redact_value(value: Any, _depth: int = 0) -> Any:
    """Recursively redact mappings/sequences by key name and strings by pattern."""
    if _depth > 8:
        return value
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if isinstance(k, str) and _SENSITIVE_KEY.search(k):
                out[k] = REDACTED
            elif isinstance(k, str) and _CONTENT_KEY.match(k):
                out[k] = f"[CONTENT {len(v) if isinstance(v, str) else '?'} chars]"
            else:
                out[k] = redact_value(v, _depth + 1)
        return out
    if isinstance(value, list | tuple):
        return type(value)(redact_value(v, _depth + 1) for v in value)
    if isinstance(value, str):
        return redact_text(value)
    return value


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            if isinstance(record.args, dict):
                record.args = redact_value(record.args)
            else:
                record.args = tuple(redact_value(a) for a in record.args)
        if isinstance(record.msg, str):
            record.msg = redact_text(record.msg)
        elif isinstance(record.msg, dict | list | tuple):
            record.msg = redact_value(record.msg)
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            record.extra_fields = redact_value(extra)
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
        }
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-7s %(name)s [%(request_id)s] %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "request_id"):
            record.request_id = request_id_var.get()
        text = super().format(record)
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict) and extra:
            text += " " + " ".join(f"{k}={v}" for k, v in extra.items())
        return redact_text(text) if record.exc_info else text


def configure_logging(level: str = "INFO", fmt: str = "text") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RedactionFilter())
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # Our middleware writes access logs with request IDs; silence uvicorn's duplicate.
    logging.getLogger("uvicorn.access").disabled = True
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers[:] = []
        lg.propagate = True
    # HTTP client libraries log request and response bodies at DEBUG; for AI calls those are document text
    # and model output. Keep them at WARNING whatever the application log level.
    for name in ("anthropic", "httpx", "httpx2", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
