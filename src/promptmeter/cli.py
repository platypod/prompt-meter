"""prompt-meter command-line entrypoint."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from . import config
from .providers import get_provider, list_providers
from .redaction import Redactor
from .shipper import Shipper

LOG_PATH = Path.home() / ".promptmeter" / "ship.log"


def _spawn_detached(argv: list[str]) -> int:
    """Re-launch ourselves fully detached and return immediately.

    Used by `--detach` so a Claude Code hook fires-and-forgets regardless of the
    shell (no `nohup &` / `start /b` / redirect needed in the hook command). The
    child re-runs the exact same args; the PROMPTMETER_DETACHED sentinel stops it
    from detaching again. stdout/stderr go to the log; stdin is closed.
    """
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log = open(LOG_PATH, "ab")
    kwargs: dict = dict(stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                        env={**os.environ, "PROMPTMETER_DETACHED": "1"}, close_fds=True)
    if os.name == "nt":
        kwargs["creationflags"] = (getattr(subprocess, "DETACHED_PROCESS", 0)
                                   | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([sys.executable, "-m", "promptmeter", *argv], **kwargs)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="prompt-meter",
        description="Ship AI coding-assistant usage telemetry to an OTLP backend.")
    p.add_argument("--provider", default="claude-code",
                   help="which assistant to read (default: claude-code)")
    p.add_argument("--list-providers", action="store_true",
                   help="list available providers and exit")
    p.add_argument("--owner", default=None,
                   help="identity these sessions belong to (default: $PROMPTMETER_OWNER "
                        "or the OS user). Stamped as the owner/user metric labels and the "
                        "Loki tenant.")
    p.add_argument("--endpoint", default=None,
                   help="OTLP gRPC endpoint (default: env / ~/.claude/settings.json)")
    p.add_argument("--tenant-prefix", default=None,
                   help="Loki tenant = <prefix><owner-slug> (default: claude-)")
    p.add_argument("--projects", default="*",
                   help="glob over the provider's project/session groups (default: all)")
    p.add_argument("--limit", type=int, default=0, help="stop after N records")
    p.add_argument("--dry-run", action="store_true", help="parse only; ship nothing")
    p.add_argument("--reset", action="store_true",
                   help="ignore saved offsets (re-ship everything)")
    p.add_argument("--metrics-only", action="store_true",
                   help="emit metrics only (no log lines); leaves the offset ledger untouched")
    p.add_argument("--insecure", action="store_true",
                   help="plaintext gRPC (e.g. a local port-forward to the gateway)")
    p.add_argument("--detach", action="store_true",
                   help="fire-and-forget: re-launch detached (logs to ~/.promptmeter/ship.log) "
                        "and return immediately. Shell-independent; used by the Claude Code hook.")
    p.add_argument("--redact-secret", action="append", default=[], metavar="STR",
                   help="literal secret to redact (repeatable)")
    p.add_argument("--redact-file", action="append", default=[], metavar="PATH",
                   help="file of newline-separated secrets to redact (repeatable)")
    p.add_argument("--redact-pattern", action="append", default=[], metavar="REGEX",
                   help="extra redaction regex (repeatable)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_providers:
        for name, desc, impl in list_providers():
            print(f"  {name:<14} {desc}{'' if impl else '  [stub]'}")
        return 0

    # Detach early (before endpoint resolution) so the caller returns instantly.
    if args.detach and os.environ.get("PROMPTMETER_DETACHED") != "1":
        return _spawn_detached(argv if argv is not None else sys.argv[1:])

    cfg = config.load(owner=args.owner, endpoint=args.endpoint,
                      insecure=args.insecure, tenant_prefix=args.tenant_prefix)
    redactor = Redactor.from_config(secrets=args.redact_secret,
                                    secret_files=args.redact_file,
                                    patterns=args.redact_pattern)
    print(f"provider={args.provider} owner={cfg.owner} tenant={cfg.tenant} "
          f"redaction={len(redactor)} literals")
    provider = get_provider(args.provider)
    Shipper(cfg, redactor).run(
        provider, dry_run=args.dry_run, reset=args.reset, limit=args.limit,
        metrics_only=args.metrics_only, projects=args.projects)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
