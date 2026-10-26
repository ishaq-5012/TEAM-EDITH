"""AI provider interface.

Business logic depends only on this protocol and on ``app.integrations.ai.gateway``, never on a vendor SDK.
A provider turns one structured request into raw text plus usage; it does not parse, trust or persist anything.
Everything a provider returns is untrusted: the gateway validates it against a strict schema and the assist
services check every evidence reference against the database before anything is shown.

Providers are given no tools. A model can only return text in the requested JSON shape, so instructions hidden
in document text have nothing to invoke.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


class AIError(RuntimeError):
    """Base for every AI failure. ``code`` is stable and shown to users; the message never contains content."""

    code = "ai_error"
    retryable = False

    def __init__(self, message: str, *, code: str | None = None, retryable: bool | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if retryable is not None:
            self.retryable = retryable


class AIProviderUnavailable(AIError):
    """AI is disabled, the provider is unknown, or it is not configured (for example, no API key)."""

    code = "ai_unavailable"


class AITimeout(AIError):
    code = "ai_timeout"
    retryable = True


class AIRateLimited(AIError):
    code = "ai_rate_limited"
    retryable = True


class AIProviderError(AIError):
    """The provider returned an error status or could not be reached."""

    code = "ai_provider_error"


class AIRefused(AIError):
    code = "ai_refused"


class AIEmptyOutput(AIError):
    code = "ai_empty_output"


class AIInvalidOutput(AIError):
    code = "ai_invalid_output"


class AIBudgetExceeded(AIError):
    code = "ai_budget_exceeded"


class AIEgressBlocked(AIError):
    """The configured egress policy does not allow the content this task needs to leave the environment."""

    code = "ai_egress_blocked"


@dataclass(frozen=True)
class StructuredRequest:
    task: str
    system: str
    user_content: str
    json_schema: dict
    max_output_tokens: int


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    stop_reason: str | None
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    request_id: str | None = None
    # Models that served the request, when the provider fell back after a refusal.
    served_by: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProviderStatus:
    name: str
    enabled: bool
    model: str | None
    detail: str
    configured: bool = False  # provider selected and credentials present (says nothing about reachability)


@runtime_checkable
class AIProvider(Protocol):
    name: str

    def status(self) -> ProviderStatus: ...

    def generate(self, request: StructuredRequest) -> ProviderResponse:
        """One attempt, no retries (the gateway owns retries). Raises an ``AIError`` subclass on failure."""
        ...

    def ping(self) -> str:
        """A cheap reachability and credentials check that spends no tokens. Returns a short detail string."""
        ...
