"""prompt-meter command-line entrypoint."""
from __future__ import annotations

import argparse

from . import config
from .providers import get_provider, list_providers
from .redaction import Redactor
from .shipper import Shipper


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
