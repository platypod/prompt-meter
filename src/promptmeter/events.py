"""Provider-neutral event model.

Every provider parses its own session/transcript format into a stream of these
objects; the rest of prompt-meter (metrics derivation, log shipping) only ever
sees `Event`, so it is fully provider-agnostic.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Usage:
    """Token counts for one assistant turn.

    Cache writes keep the 5-minute/1-hour split because they cost differently
    (1.25x vs 2x the input rate) — collapsing them loses information pricing
    needs. `cache_write` is the aggregate, for token-count metrics that don't
    care about the split.
    """
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write_5m: int = 0
    cache_write_1h: int = 0

    @property
    def cache_write(self) -> int:
        return self.cache_write_5m + self.cache_write_1h

    def is_empty(self) -> bool:
        return not (self.input or self.output or self.cache_read or self.cache_write)


@dataclass
class ToolCall:
    tool_use_id: str
    name: str


@dataclass
class ToolResult:
    tool_use_id: str
    is_error: bool = False


@dataclass
class Event:
    """One normalized transcript line.

    Carries both the structured fields used to derive metrics and the
    (redactable) body + metadata used to ship the log line to Loki.
    """
    provider: str                      # "claude-code", "copilot", …
    session_id: str
    timestamp_ns: int | None           # event time; None → skip time-stamped metrics
    role: str = ""                     # user | assistant | system
    session_title: str = ""
    project: str = ""
    model: str = ""
    usage: Usage | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    stop_reason: str = ""
    is_human_turn: bool = False

    # For the Loki log line:
    body: str = ""                     # rendered, human-readable content
    metadata: dict[str, str] = field(default_factory=dict)  # indexed/structured labels
    raw: dict = field(default_factory=dict)                 # original parsed line

    def base_labels(self) -> dict[str, str]:
        """Labels common to every metric derived from this event."""
        return {
            "provider": self.provider,
            "session_id": self.session_id,
            "session_title": self.session_title,
            "project": self.project,
        }
