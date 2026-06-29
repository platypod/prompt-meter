# prompt-meter — context for Claude

Client-side, provider-agnostic shipper for AI coding-assistant usage telemetry
(tokens / cost / tools / redacted transcripts) → an OTLP backend, per user.

**Start with [README.md](README.md)** for the goals, the data flow, the project
structure, the `ai_tx_*` schema, and how to add a provider. This file only adds
the things a README reader wouldn't infer.

## Where things live

| If you're… | Go to |
|---|---|
| Adding/changing a provider | `src/promptmeter/providers/<name>.py` + register in `providers/__init__.py` |
| Touching the shared metric schema | `src/promptmeter/metrics.py` (+ the README table) |
| Updating model prices | `src/promptmeter/pricing.py` |
| Changing what gets shipped / OTLP plumbing | `src/promptmeter/shipper.py` |
| Endpoint / owner / tenant resolution | `src/promptmeter/config.py` |
| Any operation to run | the [Makefile](Makefile) (`make help`) |

## Critical rules / non-obvious bits

- **Providers are the ONLY provider-specific code.** `metrics.py`, `shipper.py`,
  `redaction.py`, `config.py` must stay assistant-agnostic — they only ever see
  `Event`. If you find yourself special-casing Claude there, push it into the
  provider instead.
- **Metrics are back-dated gauges**, built by hand in `shipper.py` (the OTel
  metrics SDK won't backdate). Keep them stamped at the message's event time, or
  re-runs/backfill stop being idempotent and PromQL aggregation breaks.
- **`fh.tell()` is disabled inside `for line in fh`** — parsers must use a
  `readline()` loop to track resumable byte offsets (see `claude_code.py`).
- **Logs carry `x-scope-orgid: <tenant>`, metrics do not.** Loki isolates by
  tenant; Mimir isolates by the `owner` label. Don't add the tenant header to the
  metric exporter.
- **Redaction is config-driven on purpose.** Never reintroduce a dependency on any
  specific repo's secret files — it must run on anyone's machine. Add sources via
  the `--redact-*` flags / `Redactor.from_config`.
- **`--owner` is client-declared** (spoofable). For untrusted shippers, attribution
  must move server-side — see the README trust note.
- **OTel imports are lazy** (inside `shipper._otlp`) so `--list-providers` /
  `--dry-run` work without the OTLP deps installed. Keep them there.

## Relationship to platypod

This is a standalone repo, intended as a git **submodule** of the platypod
superproject (alongside `stack`, `infra`, `mediarvester`, …). The cluster side
(OTLP gateway, Mimir/Loki, the per-user scope shim, dashboards) lives in `stack`;
the contract is just OTLP + the `owner` label + the `x-scope-orgid` tenant. See
`stack/docs/observability/dashboard-multitenancy.md` for the server side.
