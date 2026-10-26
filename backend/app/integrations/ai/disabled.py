from __future__ import annotations

from app.integrations.ai.base import AIProviderUnavailable, ProviderResponse, ProviderStatus, StructuredRequest


class DisabledProvider:
    """No-AI mode. Never fabricates output; callers fall back to deterministic results."""

    name = "disabled"

    def __init__(self, detail: str = "AI assistance is disabled. All validation features work without it.") -> None:
        self._detail = detail

    def status(self) -> ProviderStatus:
        return ProviderStatus(name=self.name, enabled=False, model=None, detail=self._detail)

    def generate(self, request: StructuredRequest) -> ProviderResponse:
        raise AIProviderUnavailable("AI provider is disabled")

    def ping(self) -> str:
        raise AIProviderUnavailable("AI provider is disabled")
