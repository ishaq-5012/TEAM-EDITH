"""Provider registry. Add a provider by registering a factory; business code is unchanged."""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache

from app.core.config import get_settings
from app.integrations.ai.anthropic_provider import AnthropicProvider
from app.integrations.ai.base import AIProvider
from app.integrations.ai.disabled import DisabledProvider
from app.integrations.ai.groq_provider import GroqProvider

_FACTORIES: dict[str, Callable[[], AIProvider]] = {
    "disabled": DisabledProvider,
    "anthropic": lambda: AnthropicProvider(get_settings()),
    "groq": lambda: GroqProvider(get_settings()),
}


def register_provider(name: str, factory: Callable[[], AIProvider]) -> None:
    _FACTORIES[name] = factory
    get_provider.cache_clear()


def unregister_provider(name: str) -> None:
    if name not in ("disabled", "anthropic", "groq"):
        _FACTORIES.pop(name, None)
    get_provider.cache_clear()


@lru_cache
def get_provider() -> AIProvider:
    name = get_settings().ai_provider
    factory = _FACTORIES.get(name)
    if factory is None:
        # Unknown provider configured: fail safe to disabled rather than guessing.
        return DisabledProvider(f"Unknown AI provider {name!r} is configured; AI assistance is off.")
    return factory()
