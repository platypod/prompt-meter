"""Config-driven secret redaction.

Transcripts can contain secrets the assistant read or printed. prompt-meter
redacts before shipping. Unlike the original platypod-internal shipper (which
harvested the cluster's own values files), this is **config-driven** so anyone
can run it: point it at your own secret sources.

Sources, all optional, combined:
  - a literal list of secret strings (``--redact-secret`` / config),
  - newline-separated files of literal secrets (``--redact-file``),
  - extra regex patterns (``--redact-pattern`` / config).

Always-on generic shapes (Authorization headers, PEM private keys, common
token/bearer formats) catch the obvious cases even with no config.
"""
from __future__ import annotations

import re
from pathlib import Path

_GENERIC_PATTERNS = [
    re.compile(r"(?i)authorization:\s*\S+"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"(?i)\b(bearer|token|api[_-]?key|secret)\b\s*[=:]\s*\S+"),
]

REDACTED = "<REDACTED>"


class Redactor:
    def __init__(self, literals: list[str] | None = None,
                 patterns: list[str] | None = None):
        # Longest-first so a secret that's a substring of another is handled.
        self._literals = sorted({s for s in (literals or []) if s}, key=len, reverse=True)
        self._patterns = list(_GENERIC_PATTERNS)
        for p in (patterns or []):
            try:
                self._patterns.append(re.compile(p))
            except re.error:
                pass

    @classmethod
    def from_config(cls, secrets: list[str] | None = None,
                    secret_files: list[str] | None = None,
                    patterns: list[str] | None = None) -> "Redactor":
        literals = list(secrets or [])
        for f in (secret_files or []):
            try:
                literals += [ln.strip() for ln in Path(f).expanduser().read_text().splitlines()
                             if ln.strip() and not ln.startswith("#")]
            except OSError:
                pass
        return cls(literals=literals, patterns=patterns)

    def redact(self, text: str) -> str:
        if not text:
            return text
        for s in self._literals:
            text = text.replace(s, REDACTED)
        for p in self._patterns:
            text = p.sub(REDACTED, text)
        return text

    def __len__(self) -> int:
        return len(self._literals)
