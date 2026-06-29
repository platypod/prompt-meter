"""Hermes provider — STUB.

TODO: parse Hermes session data into `Event`s. Same contract as the other
providers: discover sessions, yield (offset, Event) per record.
"""
from __future__ import annotations

from typing import Iterator

from .base import Provider, Session


class HermesProvider(Provider):
    name = "hermes"
    description = "Hermes (not yet implemented)"
    implemented = False

    def discover(self, projects: str = "*"):
        raise NotImplementedError("hermes provider not implemented yet")

    def parse(self, session: Session, start_offset: int = 0) -> Iterator:
        raise NotImplementedError("hermes provider not implemented yet")
