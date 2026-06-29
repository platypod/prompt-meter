# prompt-meter

Ship **AI coding-assistant usage telemetry** — tokens, cost, tool usage, and
(redacted) transcripts — from your machine to an **OTLP** backend, **per user**.
Provider-agnostic: Claude Code today, Copilot / Hermes / others next.

It's the client half of the platypod observability stack: prompt-meter runs on a
laptop and pushes; the cluster (Mimir + Loki + Grafana, with a per-user scope
shim) stores and visualises. The only contract between them is *OTLP + an `owner`
label + an `x-scope-orgid` tenant* — so prompt-meter has no dependency on the
cluster repo and anyone can run it against their own endpoint.

## Goals

- **One tool, many providers.** Each assistant is a thin adapter; the metric
  schema, cost model, redaction, and shipping are shared.
- **Per-user attribution.** Every metric carries an `owner` label and every
  transcript goes to a `claude-<owner>` Loki tenant, so a multi-tenant backend can
  show each user only their own data (admins see all).
- **Self-contained & safe to share.** Secret redaction is **config-driven** (your
  secrets, not someone else's repo), and shipping is incremental + idempotent.

## How it works

```
~/.claude/projects/*.jsonl ──▶ Provider.parse ──▶ Event stream ──┬─▶ metrics.derive ─▶ ai_tx_* gauges ─▶ OTLP/Mimir
   (per-provider format)        (normalized)                     └─▶ redact + body   ─▶ log lines      ─▶ OTLP/Loki (tenant=claude-<owner>)
```

A **provider** only does two things: discover a user's session files and parse
each into provider-neutral `Event`s. Everything downstream is shared and never
needs to know which assistant produced the data.

Metrics are emitted as **gauges stamped at each message's own event time** (not
process-clock counters) so they stay idempotent across re-runs/backfill and
aggregate in PromQL with `sum_over_time` / `quantile_over_time` / max−min.

## Project structure

```
prompt-meter/
├── Makefile                  # every operation (build, ship, setup) — see `make help`
├── pyproject.toml            # installable: `prompt-meter` / `promptmeter` console scripts
├── README.md  CLAUDE.md
└── src/promptmeter/
    ├── cli.py                # argparse entrypoint
    ├── config.py             # endpoint/owner/headers/tenant resolution (env + ~/.claude/settings.json)
    ├── events.py             # the provider-neutral Event / Usage / Tool* model
    ├── metrics.py            # Event → ai_tx_* gauges (shared, provider-agnostic)
    ├── pricing.py            # per-provider/model rate tables → notional USD cost
    ├── redaction.py          # config-driven secret redaction
    ├── shipper.py            # OTLP export (logs + back-dated metric gauges) + offset ledger
    ├── contrib/
    │   └── claude_hook.py    # install/print the Claude Code SessionEnd hook
    └── providers/
        ├── base.py           # Provider ABC (discover + parse)
        ├── __init__.py       # registry
        ├── claude_code.py    # implemented
        ├── copilot.py        # stub
        └── hermes.py         # stub
```

## The metric schema (`ai_tx_*`)

| Metric | Key labels | Meaning |
|---|---|---|
| `ai_tx_tokens` | `kind`, `model`, `owner`, `provider`, `session_*` | per-message token counts |
| `ai_tx_cost_usd` / `_by_kind` | `model`, `owner`, … | notional API-equivalent cost |
| `ai_tx_tool_calls` | `tool_name`, … | tool invocations |
| `ai_tx_tool_latency_seconds` / `_tool_errors` | `tool_name`, … | tool timing / errors |
| `ai_tx_turns` | `owner`, … | human turns |
| `ai_tx_stop_reason` | `stop_reason`, … | assistant stop reasons |
| `ai_tx_event_epoch_seconds` | `owner`, … | message event epoch → session duration / time-of-day |

`owner` is the per-user isolation key (a parallel `user` label is emitted too, for
admin "focus on one user" dashboard filters, since the scope proxy overrides
`owner`). Costs are notional (`tokens × list price`), not a subscription bill.

## Install

`prompt-meter` is a normal Python package — the wheel + CLI work the same on
**Windows, macOS, and Linux**. CI publishes each tag to **GitHub Releases** (via
GitHub Actions + `GITHUB_TOKEN`, no PyPI account). Install a tag straight from
GitHub:

```sh
pipx install "git+https://github.com/platypod/prompt-meter@v0.1.0"   # isolated, on PATH
# or:  pip install "git+https://github.com/platypod/prompt-meter@v0.1.0"
```

Prefer a prebuilt artifact? Every release attaches the wheel — grab
`prompt_meter-<version>-py3-none-any.whl` from the release page and
`pipx install ./prompt_meter-*.whl`. Or build one yourself: `make build` (Unix) /
`python -m build` (any OS) → `dist/`.

> The **Makefile is a Unix dev / CI convenience only** (it assumes a `.venv/bin`
> layout and POSIX tools). Windows users don't need it: install the wheel and use
> the `prompt-meter` CLI (or `python -m promptmeter`) per the sections below.

## Configuration

Set this up **first** — the Usage commands below assume an endpoint is
resolvable, so configure before you ship.

- **Endpoint / auth**: `--endpoint` / `OTEL_EXPORTER_OTLP_ENDPOINT`, then
  `~/.claude/settings.json` `env` (its `OTEL_*` block) as a fallback.
- **Owner**: `--owner` / `$PROMPTMETER_OWNER` / OS user. Drives the `owner` label
  and the `claude-<owner>` Loki tenant.
- **Redaction** (config-driven, combined): `--redact-secret STR`,
  `--redact-file PATH`, `--redact-pattern REGEX`, plus always-on generic shapes
  (Authorization headers, PEM keys, bearer/token forms).
- **State**: incremental offset ledger at `~/.promptmeter/state.json`
  (`$PROMPTMETER_STATE`); `--reset` re-ships everything.

### Endpoint examples

**Plaintext, no auth** — e.g. a local port-forward straight to the gateway
(`kubectl -n dev-platypod port-forward svc/opentelemetry-collector-gateway 4317:4317`):

```sh
export OTEL_EXPORTER_OTLP_ENDPOINT=localhost:4317
prompt-meter --owner dave --insecure
```

**TLS + Basic auth** — through the public platypod gateway (Authelia Basic-auth
LLDAP service account):

```sh
export OTEL_EXPORTER_OTLP_ENDPOINT=opentelemetry-collector-grpc.platypod.ovh:443
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic $(printf 'user:pass' | base64)"
prompt-meter --owner dave
```

On **Windows (PowerShell)** the same vars, with PowerShell's base64:

```powershell
$env:OTEL_EXPORTER_OTLP_ENDPOINT = "opentelemetry-collector-grpc.platypod.ovh:443"
$env:OTEL_EXPORTER_OTLP_HEADERS  = "Authorization=Basic " +
  [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("user:pass"))
prompt-meter --owner dave        # add --insecure for a plaintext localhost endpoint
```

If you already run Claude Code's own telemetry, both of these are likely set in
`~/.claude/settings.json` `env` already — prompt-meter reads them as a fallback,
so you can skip the exports.

## Usage

Once installed (any OS), drive it with the CLI:

```sh
prompt-meter --list-providers
prompt-meter --owner dave --dry-run        # parse only, ship nothing
prompt-meter --owner dave                  # ship (uses the env configured above)
prompt-meter --owner dave --reset          # re-ship everything
```

`python -m promptmeter …` is equivalent. Full flags:
`--provider claude-code --owner dave [--dry-run|--reset|--limit N|--metrics-only|--insecure]`.

**Auto-ship on every Claude Code session close** — works on Windows, macOS, and
Linux. The hook is a plain `prompt-meter … --detach`; the tool re-launches itself
detached (logging to `~/.promptmeter/ship.log`) and returns instantly, so it never
delays session close and **doesn't depend on the shell** (no `nohup &` / `start /b`):

```sh
prompt-meter-hook install --owner dave     # = python -m promptmeter.contrib.claude_hook install
```

### Unix dev shortcut (Makefile)

On Unix the Makefile wraps the above against a local `.venv` (`make help` lists all):

```sh
make install          # venv + editable install (+ dev tools)
make ship OWNER=dave  # = prompt-meter --owner dave
make build            # build the wheel + sdist into dist/ (the CI artifact target)
```

## Adding a provider

1. Subclass `Provider` (`providers/base.py`): implement `discover()` and `parse()`,
   normalizing the provider's records into `Event`s.
2. Register it in `providers/__init__.py`.
3. Add its model rates to `pricing.py`.

Nothing else changes — metrics, redaction, shipping, and dashboards are shared.

## Trust note

`--owner` is **client-declared** (a shipper can claim any identity). Fine for
trusted users. For untrusted shippers, stamp `owner`/tenant **server-side** at the
gateway from the authenticated identity instead — the client tool is unchanged;
the trust boundary just moves to the cluster.
