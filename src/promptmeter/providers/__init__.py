"""Provider registry.

Register each provider here so the CLI can resolve `--provider <name>` and list
the available ones. New providers: implement `Provider`, import it, add to the
`_PROVIDERS` tuple.
"""
from __future__ import annotations

from .base import Provider, Session
from .claude_code import ClaudeCodeProvider
from .copilot import CopilotProvider
from .hermes import HermesProvider

_PROVIDERS: tuple[type[Provider], ...] = (
    ClaudeCodeProvider,
    CopilotProvider,
    HermesProvider,
)

PROVIDERS: dict[str, type[Provider]] = {p.name: p for p in _PROVIDERS}


def get_provider(name: str) -> Provider:
    try:
        return PROVIDERS[name]()
    except KeyError:
        raise SystemExit(
            f"unknown provider {name!r}; available: {', '.join(PROVIDERS)}"
        )


def list_providers() -> list[tuple[str, str, bool]]:
    """(name, description, implemented) for each registered provider."""
    out = []
    for name, cls in PROVIDERS.items():
        out.append((name, cls.description, getattr(cls, "implemented", True)))
    return out


__all__ = ["Provider", "Session", "PROVIDERS", "get_provider", "list_providers"]
