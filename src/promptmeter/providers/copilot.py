"""GitHub Copilot provider — STUB.

TODO: locate and parse Copilot's local session/usage data and normalize it into
`Event`s (token usage, tool/agent calls, timestamps). Likely sources to explore:
the Copilot Chat logs / the editor's per-workspace state. Map fields onto the
shared model so the same metrics + dashboards apply.
"""
from __future__ import annotations

from typing import Iterator

from .base import Provider, Session


class CopilotProvider(Provider):
    name = "copilot"
    description = "GitHub Copilot (not yet implemented)"
    implemented = False

    def discover(self, projects: str = "*"):
        raise NotImplementedError("copilot provider not implemented yet")

    def parse(self, session: Session, start_offset: int = 0) -> Iterator:
        raise NotImplementedError("copilot provider not implemented yet")
