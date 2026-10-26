"""Groq via its OpenAI-compatible Chat Completions API, called with httpx (no SDK).

One attempt per ``generate`` call; the gateway owns retries, budgets and schema validation. Output is requested as
JSON matching the task schema (``response_format: json_schema``), and the request carries no tools. A refusal from
the model is reported as ``AIRefused``; a response cut off by the token limit is reported with
``stop_reason="max_tokens"`` so the gateway treats it like any other truncated answer.

The API key comes from settings only (never from a request), and neither the key nor any content is logged here.
"""

from __future__ import annotations

from typing import Any

import httpx

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

DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "openai/gpt-oss-120b"
# Groq's reasoning models accept a reasoning effort; others ignore the field, so it is only sent to them.
REASONING_MODELS = ("openai/gpt-oss",)


class GroqProvider:
    name = "groq"

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        self._settings = settings
        self._transport = transport  # tests pass a mock transport; production uses the network

    @property
    def model(self) -> str:
        # The shared default model id is a Claude model; fall back to a Groq model rather than sending it to Groq.
        m = self._settings.ai_model
        return DEFAULT_MODEL if m.startswith("claude") else m

    # ------------------------------------------------------------------ status

    def status(self) -> ProviderStatus:
        s = self._settings
        if s.ai_api_key is None or not s.ai_api_key.get_secret_value().strip():
            return ProviderStatus(
                name=self.name, enabled=False, model=self.model,
                detail="No API key is configured (VERIFYFLOW_AI_API_KEY). AI assistance is off; everything else "
                "works.",
            )
        return ProviderStatus(
            name=self.name, enabled=True, configured=True, model=self.model,
            detail=f"Groq ({self.model}) via the OpenAI-compatible API",
        )

    # ------------------------------------------------------------------ http

    def _client(self) -> httpx.Client:
        s = self._settings
        if s.ai_api_key is None or not s.ai_api_key.get_secret_value().strip():
            raise AIProviderUnavailable("No API key is configured")
        return httpx.Client(
            base_url=(s.ai_base_url or DEFAULT_BASE_URL).rstrip("/"),
            headers={"Authorization": f"Bearer {s.ai_api_key.get_secret_value()}"},
            timeout=s.ai_timeout_seconds,
            transport=self._transport,
        )

    @staticmethod
    def _map_status(code: int) -> AIError:
        """Translate HTTP failures into provider-neutral errors. Messages carry no request content."""
        if code == 429:
            return AIRateLimited("The AI provider is rate limiting requests")
        if code in (401, 403):
            return AIProviderError("The AI provider rejected the configured credentials", code="ai_auth_failed")
        if code == 404:
            return AIProviderError("The configured model is not available", code="ai_model_unavailable")
        if code in (400, 413, 422):
            return AIProviderError("The AI provider rejected the request", code="ai_bad_request")
        transient = code >= 500 or code in (408, 409)
        return AIProviderError(f"The AI provider returned HTTP {code}", retryable=transient)

    def _send(self, method: str, path: str, json: dict | None = None) -> dict:
        try:
            with self._client() as client:
                r = client.request(method, path, json=json)
        except httpx.TimeoutException:
            raise AITimeout("The AI provider did not respond in time") from None
        except httpx.TransportError:
            raise AIProviderError(
                "The AI provider could not be reached", code="ai_unreachable", retryable=True
            ) from None
        if r.status_code >= 400:
            raise self._map_status(r.status_code)
        try:
            return r.json()
        except ValueError:
            raise AIProviderError("The AI provider returned a malformed response", retryable=True) from None

    # ------------------------------------------------------------------ calls

    def generate(self, request: StructuredRequest) -> ProviderResponse:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user_content},
            ],
            "max_completion_tokens": request.max_output_tokens,
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": request.task.replace(".", "_")[:64] or "output", "schema": request.json_schema},
            },
        }
        if self.model.startswith(REASONING_MODELS):
            body["reasoning_effort"] = self._settings.ai_effort
        data = self._send("POST", "/chat/completions", body)

        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        if message.get("refusal"):
            raise AIRefused("The model declined the request")
        finish = choice.get("finish_reason")
        usage = data.get("usage") or {}
        return ProviderResponse(
            text=message.get("content") or "",
            stop_reason="max_tokens" if finish == "length" else finish,
            model=data.get("model", self.model),
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
            request_id=(data.get("x_groq") or {}).get("id") or data.get("id"),
        )

    def ping(self) -> str:
        data = self._send("GET", f"/models/{self.model}")
        return f"Reachable; model {data.get('id', self.model)} is available"
