"""Install (or print) a Claude Code ``SessionEnd`` hook that ships telemetry.

Because shipping is incremental + idempotent (offset ledger), it's safe to fire
on every session close instead of remembering to run it. ``install`` merges the
hook into ``~/.claude/settings.json`` idempotently, backing the file up first.

Usage:
    python -m promptmeter.contrib.claude_hook print   [--owner X]
    python -m promptmeter.contrib.claude_hook install [--owner X]
"""
from __future__ import annotations

import argparse
import getpass
import json
import shutil
import time
from pathlib import Path

SETTINGS = Path.home() / ".claude" / "settings.json"
LOG_DIR = Path.home() / ".promptmeter"
MARKER = "prompt-meter"  # identifies our hook so install stays idempotent


def hook_command(owner: str) -> str:
    """A plain, **shell-independent** command — `--detach` makes prompt-meter
    re-launch itself in the background (logging to ~/.promptmeter/ship.log) and
    return immediately, so the gRPC flush never delays CLI exit and no `nohup &`
    / `start /b` / redirect (which differ per shell) is needed."""
    return f"prompt-meter --provider claude-code --owner {owner} --detach"


def hook_entry(owner: str) -> dict:
    return {"hooks": [{"type": "command", "command": hook_command(owner)}]}


def do_print(owner: str) -> None:
    print(json.dumps({"hooks": {"SessionEnd": [hook_entry(owner)]}}, indent=2))


def do_install(owner: str) -> None:
    settings = {}
    if SETTINGS.exists():
        settings = json.loads(SETTINGS.read_text())
        backup = SETTINGS.with_suffix(f".json.bak.{int(time.time())}")
        shutil.copy2(SETTINGS, backup)
        print(f"backed up settings → {backup}")
    hooks = settings.setdefault("hooks", {})
    session_end = hooks.setdefault("SessionEnd", [])
    if any(MARKER in h.get("command", "")
           for entry in session_end for h in entry.get("hooks", [])):
        print("prompt-meter SessionEnd hook already present — nothing to do.")
        return
    session_end.append(hook_entry(owner))
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)  # so the hook's `>>` redirect succeeds
    SETTINGS.write_text(json.dumps(settings, indent=2))
    print(f"installed SessionEnd hook (owner={owner}). Restart Claude Code to load it.")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="claude_hook")
    p.add_argument("action", choices=["print", "install"])
    p.add_argument("--owner", default=getpass.getuser())
    args = p.parse_args(argv)
    (do_print if args.action == "print" else do_install)(args.owner)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
