"""The single guarded path to an AI provider.

Every call goes through ``AIGateway.call``, which in order:
1. refuses when the provider is disabled or not configured (``AIProviderUnavailable``);
2. enforces the input size cap, process-wide and per-user rate limits, and the daily spend budget
   (estimated before the call from the configured prices, so a call that could overrun is never made);
3. calls the provider with a per-attempt timeout and a bounded number of retries with exponential backoff,
   only for retryable failures (timeouts, provider rate limits, 5xx, connection errors);
4. rejects a refusal, empty output, truncated output, invalid JSON or JSON that doesn't match the task's strict
   Pydantic schema. Nothing unvalidated is returned;
5. records provider health (last success, last error code, consecutive failures) for the status endpoint.

Logs carry the task, provider, model, token counts, cost, duration and error code. Never prompts or output.
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.integrations.ai.base import (
    AIBudgetExceeded,
    AIEmptyOutput,
    AIError,
    AIInvalidOutput,
    AIProvider,
    AIProviderUnavailable,
    AIRateLimited,
    ProviderResponse,
    StructuredRequest,
)

log = logging.getLogger("verifyflow.ai")

T = TypeVar("T", bound=BaseModel)

CHARS_PER_TOKEN_ESTIMATE = 3  # conservative: overestimates tokens, so the budget check errs on the safe side
BACKOFF_BASE_SECONDS = 0.5
BACKOFF_MAX_SECONDS = 8.0


def estimate_cost_usd(settings: Settings, input_tokens: int, output_tokens: int) -> float:
    return (
        input_tokens * settings.ai_input_usd_per_mtok + output_tokens * settings.ai_output_usd_per_mtok
    ) / 1_000_000


# ------------------------------------------------------------------ process-wide state


class _RateLimiter:
    """Sliding-window limits: per process per minute and per user per hour. In-memory, like login throttling's
    first line of defence; a multi-process deployment should also rate limit at the gateway/proxy."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._global: deque[float] = deque()
        self._users: dict[str, deque[float]] = {}

    def reset(self) -> None:
        with self._lock:
            self._global.clear()
            self._users.clear()

    def acquire(self, user_id: str, per_minute: int, per_user_hour: int, now: float) -> None:
        with self._lock:
            while self._global and now - self._global[0] >= 60:
                self._global.popleft()
            q = self._users.setdefault(user_id, deque())
            while q and now - q[0] >= 3600:
                q.popleft()
            if len(self._global) >= per_minute:
                raise AIRateLimited("Too many AI requests right now; try again in a minute", code="ai_local_rate_limit")
            if len(q) >= per_user_hour:
                raise AIRateLimited("You have reached your hourly AI request limit", code="ai_user_rate_limit")
            self._global.append(now)
            q.append(now)


@dataclass
class Health:
    calls: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    last_success_at: str | None = None
    last_error_at: str | None = None
    last_error_code: str | None = None
    last_check_at: str | None = None
    last_check_ok: bool | None = None
    last_check_detail: str | None = None

    @property
    def state(self) -> str:
        if self.calls == 0 and self.last_check_ok is None:
            return "unknown"
        if self.consecutive_failures >= 3 or (self.last_check_ok is False and self.consecutive_failures):
            return "failing"
        if self.consecutive_failures or self.last_check_ok is False:
            return "degraded"
        return "healthy"

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "calls": self.calls,
            "failures": self.failures,
            "consecutive_failures": self.consecutive_failures,
            "last_success_at": self.last_success_at,
            "last_error_at": self.last_error_at,
            "last_error_code": self.last_error_code,
            "last_check_at": self.last_check_at,
            "last_check_ok": self.last_check_ok,
            "last_check_detail": self.last_check_detail,
        }


_limiter = _RateLimiter()
_health = Health()
_health_lock = threading.Lock()


def health() -> Health:
    return _health


def reset_state() -> None:
    """Clear rate-limit windows and health counters (tests, or after reconfiguration)."""
    global _health
    _limiter.reset()
    with _health_lock:
        _health = Health()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _record(ok: bool, code: str | None = None) -> None:
    with _health_lock:
        _health.calls += 1
        if ok:
            _health.consecutive_failures = 0
            _health.last_success_at = _now_iso()
        else:
            _health.failures += 1
            _health.consecutive_failures += 1
            _health.last_error_at = _now_iso()
            _health.last_error_code = code


# ------------------------------------------------------------------ gateway


@dataclass(frozen=True)
class GatewayResult(Generic[T]):
    output: T
    response: ProviderResponse
    attempts: int
    duration_ms: int
    cost_usd: float


class AIGateway:
    def __init__(
        self,
        provider: AIProvider,
        settings: Settings,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.provider = provider
        self.settings = settings
        self._sleep = sleep
        self._clock = clock

    def preflight(self, request: StructuredRequest, *, spent_today_usd: float) -> float:
        """Checks that need no network. Returns the estimated worst-case cost of the call."""
        status = self.provider.status()
        if not status.enabled:
            raise AIProviderUnavailable(status.detail)
        s = self.settings
        chars = len(request.system) + len(request.user_content)
        if chars > s.ai_max_input_chars + 4_000:  # task prompts and schema overhead are bounded separately
            raise AIBudgetExceeded("The request is larger than the configured input limit", code="ai_input_too_large")
        estimate = estimate_cost_usd(
            s, math.ceil(chars / CHARS_PER_TOKEN_ESTIMATE), request.max_output_tokens
        )
        if spent_today_usd + estimate > s.ai_daily_budget_usd:
            raise AIBudgetExceeded(
                f"Today's AI budget (${s.ai_daily_budget_usd:.2f}) would be exceeded; "
                f"${spent_today_usd:.4f} already spent"
            )
        return estimate

    def call(
        self, request: StructuredRequest, output_model: type[T], *, user_id: str, spent_today_usd: float
    ) -> GatewayResult[T]:
        s = self.settings
        self.preflight(request, spent_today_usd=spent_today_usd)
        _limiter.acquire(user_id, s.ai_rate_limit_per_minute, s.ai_user_rate_limit_per_hour, self._clock())

        started = self._clock()
        attempts = 0
        while True:
            attempts += 1
            try:
                response = self.provider.generate(request)
                output = self._parse(response, output_model)
            except AIError as exc:
                if exc.retryable and attempts <= s.ai_max_retries:
                    delay = min(BACKOFF_BASE_SECONDS * 2 ** (attempts - 1), BACKOFF_MAX_SECONDS)
                    log.warning(
                        "AI %s attempt %d failed (%s); retrying in %.1fs", request.task, attempts, exc.code, delay,
                        extra={"extra_fields": {"ai_task": request.task, "error_code": exc.code}},
                    )
                    self._sleep(delay)
                    continue
                _record(False, exc.code)
                log.warning(
                    "AI %s failed after %d attempt(s): %s", request.task, attempts, exc.code,
                    extra={"extra_fields": {"ai_task": request.task, "error_code": exc.code, "attempts": attempts}},
                )
                exc.attempts = attempts  # type: ignore[attr-defined]
                raise
            break

        duration_ms = int((self._clock() - started) * 1000)
        cost = estimate_cost_usd(s, response.input_tokens, response.output_tokens)
        _record(True)
        log.info(
            "AI %s ok: %s in=%d out=%d cost=$%.5f %dms attempts=%d",
            request.task, response.model, response.input_tokens, response.output_tokens, cost, duration_ms, attempts,
            extra={
                "extra_fields": {
                    "ai_task": request.task,
                    "ai_model": response.model,
                    # Not "*_tokens": key-based redaction treats any "token" key as a credential.
                    "usage_in": response.input_tokens,
                    "usage_out": response.output_tokens,
                    "cost_usd": round(cost, 6),
                }
            },
        )
        return GatewayResult(
            output=output, response=response, attempts=attempts, duration_ms=duration_ms, cost_usd=cost
        )

    @staticmethod
    def _parse(response: ProviderResponse, output_model: type[T]) -> T:
        text = (response.text or "").strip()
        if response.stop_reason == "max_tokens":
            raise AIInvalidOutput("The model's answer was cut off before it was complete", code="ai_truncated_output")
        if not text:
            raise AIEmptyOutput("The model returned no content")
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, RecursionError):
            raise AIInvalidOutput("The model's answer was not valid JSON") from None
        try:
            return output_model.model_validate(data)
        except ValidationError as exc:
            # Field locations only: the offending values are model output and are not echoed.
            where = sorted({".".join(str(p) for p in e["loc"]) or "(root)" for e in exc.errors()})[:5]
            raise AIInvalidOutput(
                f"The model's answer did not match the expected schema ({', '.join(where)})"
            ) from None

    def ping(self) -> str:
        status = self.provider.status()
        with _health_lock:
            _health.last_check_at = _now_iso()
        if not status.enabled:
            with _health_lock:
                _health.last_check_ok = False
                _health.last_check_detail = status.detail
            raise AIProviderUnavailable(status.detail)
        try:
            detail = self.provider.ping()
        except AIError as exc:
            with _health_lock:
                _health.last_check_ok = False
                _health.last_check_detail = exc.code
            raise
        with _health_lock:
            _health.last_check_ok = True
            _health.last_check_detail = detail
        return detail
