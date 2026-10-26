"""Claude via the official Anthropic Python SDK.

One attempt per ``generate`` call: the SDK's own retries are turned off so the gateway's bounded retry policy is
the only one, and the configured timeout is a real per-attempt ceiling. Output is constrained with structured
outputs (``output_config.format``) and the request carries no tools. A refusal (``stop_reason == "refusal"``) is
reported as ``AIRefused``; with ``ai_refusal_fallback`` the API first retries a declined request server-side on
the provider's recommended fallback model.

The API key comes from settings only (never from a request), and neither the key nor any content is logged here.
"""

from __future__ import annotations

from functools import cached_property
from typing import Any

from app.core.config import Settings
from app.integrations.ai.base import (
    AIError,
    AIProviderError,
    AIProviderUnavailable,
    AIRateLimited,
    AIRefused,
    AITimeout,
    ProviderResponse,
    ProviderStatus,
    StructuredRequest,
)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


def _sdk_version() -> str | None:
    try:
        import anthropic

        return anthropic.__version__
    except ImportError:
        return None


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self._settings = settings
        self._injected_client = client  # tests pass a stand-in; production builds the SDK client lazily

    # ------------------------------------------------------------------ status

    def status(self) -> ProviderStatus:
        s = self._settings
        if _sdk_version() is None and self._injected_client is None:
            return ProviderStatus(
                name=self.name, enabled=False, model=s.ai_model,
                detail="The anthropic package is not installed. AI assistance is off; everything else works.",
            )
        if s.ai_api_key is None or not s.ai_api_key.get_secret_value().strip():
            return ProviderStatus(
                name=self.name, enabled=False, model=s.ai_model,
                detail="No API key is configured (VERIFYFLOW_AI_API_KEY). AI assistance is off; everything else "
                "works.",
            )
        return ProviderStatus(
            name=self.name, enabled=True, configured=True, model=s.ai_model,
            detail=f"Claude ({s.ai_model}) via the Anthropic SDK {_sdk_version() or ''}".strip(),
        )

    # ------------------------------------------------------------------ client

    @cached_property
    def _client(self) -> Any:
        if self._injected_client is not None:
            return self._injected_client
        import anthropic

        s = self._settings
        if s.ai_api_key is None:
            raise AIProviderUnavailable("No API key is configured")
        kwargs: dict[str, Any] = {
            "api_key": s.ai_api_key.get_secret_value(),
            "timeout": s.ai_timeout_seconds,
            "max_retries": 0,  # the gateway owns retries
        }
        if s.ai_base_url:
            kwargs["base_url"] = s.ai_base_url
        return anthropic.Anthropic(**kwargs)

    # ------------------------------------------------------------------ calls

    def _map_error(self, exc: Exception) -> AIError:
        """Translate SDK exceptions into provider-neutral errors. Messages carry no request content."""
        import anthropic

        if isinstance(exc, anthropic.APITimeoutError):
            return AITimeout("The AI provider did not respond in time")
        if isinstance(exc, anthropic.RateLimitError):
            return AIRateLimited("The AI provider is rate limiting requests")
        if isinstance(exc, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
            return AIProviderError("The AI provider rejected the configured credentials", code="ai_auth_failed")
        if isinstance(exc, anthropic.NotFoundError):
            return AIProviderError("The configured model is not available", code="ai_model_unavailable")
        if isinstance(exc, anthropic.BadRequestError):
            return AIProviderError("The AI provider rejected the request", code="ai_bad_request")
        if isinstance(exc, anthropic.APIStatusError):
            transient = exc.status_code >= 500 or exc.status_code in (408, 409, 529)
            return AIProviderError(f"The AI provider returned HTTP {exc.status_code}", retryable=transient)
        if isinstance(exc, anthropic.APIConnectionError):
            return AIProviderError("The AI provider could not be reached", code="ai_unreachable", retryable=True)
        return AIProviderError(f"Unexpected AI client error ({exc.__class__.__name__})")

    def generate(self, request: StructuredRequest) -> ProviderResponse:
        import anthropic

        s = self._settings
        params: dict[str, Any] = {
            "model": s.ai_model,
            "max_tokens": request.max_output_tokens,
            "system": request.system,
            "messages": [{"role": "user", "content": request.user_content}],
            "output_config": {
                "effort": s.ai_effort,
                "format": {"type": "json_schema", "schema": request.json_schema},
            },
        }
        try:
            if s.ai_refusal_fallback:
                message = self._client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **params)
            else:
                message = self._client.messages.create(**params)
        except anthropic.APIError as exc:
            raise self._map_error(exc) from None

        stop = getattr(message, "stop_reason", None)
        if stop == "refusal":
            details = getattr(message, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            raise AIRefused(f"The model declined the request{f' ({category})' if category else ''}")
        text = "".join(getattr(b, "text", "") for b in message.content if getattr(b, "type", None) == "text")
        served_by = [
            getattr(getattr(b, "to", None), "model", "")
            for b in message.content
            if getattr(b, "type", None) == "fallback"
        ]
        usage = getattr(message, "usage", None)
        return ProviderResponse(
            text=text,
            stop_reason=stop,
            model=getattr(message, "model", s.ai_model),
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            request_id=getattr(message, "_request_id", None),
            served_by=[m for m in served_by if m],
        )

    def ping(self) -> str:
        import anthropic

        try:
            model = self._client.models.retrieve(self._settings.ai_model)
        except anthropic.APIError as exc:
            raise self._map_error(exc) from None
        return f"Reachable; model {getattr(model, 'id', self._settings.ai_model)} is available"
