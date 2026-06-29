"""Provider interface.

A provider knows how to (1) find a user's session files for one assistant and
(2) turn each into a stream of normalized `Event`s. Everything else — metrics,
redaction, OTLP shipping, the offset ledger — is provider-agnostic and lives in
`promptmeter.core` modules.

Add a provider by subclassing `Provider`, implementing `discover` + `parse`, and
registering it in `promptmeter/providers/__init__.py`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from ..events import Event


@dataclass
class Session:
    """A single discovered session source (usually a transcript file)."""
    path: Path
    # Stable id used to key the byte-offset ledger so tailing is incremental.
    key: str


class Provider(ABC):
    #: Stable, kebab-case identifier — also the value of the `provider` metric label.
    name: str = ""
    #: One-line human description, shown by `prompt-meter --list-providers`.
    description: str = ""

    @abstractmethod
    def discover(self, projects: str = "*") -> Iterable[Session]:
        """Yield the session sources to ship (oldest first is preferred)."""
        raise NotImplementedError

    @abstractmethod
    def parse(self, session: Session, start_offset: int = 0) -> Iterator[tuple[int, Event]]:
        """Yield (new_byte_offset, Event) for each record after `start_offset`.

        The offset is the resumable position saved to the ledger after the event
        is confirmed shipped, so a later run tails only new lines.
        """
        raise NotImplementedError
