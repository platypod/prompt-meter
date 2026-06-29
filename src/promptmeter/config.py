"""Runtime configuration: where to ship, as whom, under which tenant.

Resolution order for the OTLP endpoint + headers: process env wins, then (as a
convenience for Claude Code users) ``~/.claude/settings.json``'s ``env`` block,
which already holds the gateway endpoint + Basic-auth header.
"""
from __future__ import annotations

import getpass
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    endpoint: str
    owner: str
    headers: dict[str, str] = field(default_factory=dict)
    insecure: bool = False
    tenant_prefix: str = "claude-"   # Loki tenant = f"{prefix}{slug(owner)}"
    state_path: Path = field(default_factory=lambda: Path(
        os.environ.get("PROMPTMETER_STATE",
                       str(Path.home() / ".promptmeter" / "state.json"))))

    @property
    def tenant(self) -> str:
        slug = re.sub(r"[^a-z0-9-]+", "-", self.owner.lower()).strip("-")
        return f"{self.tenant_prefix}{slug}"


def _load_claude_settings() -> dict[str, str]:
    try:
        data = json.loads((Path.home() / ".claude" / "settings.json").read_text())
        return data.get("env", {}) or {}
    except (OSError, json.JSONDecodeError):
        return {}


def load(owner: str | None = None, endpoint: str | None = None,
         insecure: bool = False, tenant_prefix: str | None = None) -> Config:
    env = _load_claude_settings()

    ep = (endpoint or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
          or env.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")).strip()
    if not ep:
        raise SystemExit("no OTLP endpoint: pass --endpoint or set "
                         "OTEL_EXPORTER_OTLP_ENDPOINT (env or ~/.claude/settings.json)")
    ep = re.sub(r"^https?://", "", ep)

    headers: dict[str, str] = {}
    raw = os.environ.get("OTEL_EXPORTER_OTLP_HEADERS") or env.get("OTEL_EXPORTER_OTLP_HEADERS", "")
    for pair in raw.split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            headers[k.strip().lower()] = v.strip()  # gRPC metadata keys must be lowercase

    owner = (owner or os.environ.get("PROMPTMETER_OWNER") or getpass.getuser())
    return Config(
        endpoint=ep, owner=owner, headers=headers, insecure=insecure,
        tenant_prefix=(tenant_prefix if tenant_prefix is not None else "claude-"),
    )
