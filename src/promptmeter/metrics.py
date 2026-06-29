"""Derive the shared `ai_tx_*` metric series from normalized events.

Emitted as gauges stamped at each message's own event time (not process-clock
counters) so they stay idempotent across re-runs/backfill and aggregate in PromQL
with sum_over_time / quantile_over_time / max-min. Every series carries the
`owner` (+ `provider`) label, which is what the platypod scope shim filters on
for per-user dashboard isolation.
"""
from __future__ import annotations

from typing import Callable

from . import pricing
from .events import Event

# add(name, value, ts_ns, **labels)
Emit = Callable[..., None]


def derive(ev: Event, owner: str, tool_use_times: dict[str, int], add: Emit) -> None:
    ts = ev.timestamp_ns
    if ts is None:
        return
    base = ev.base_labels()
    base["owner"] = owner
    base["user"] = owner  # parallel, non-enforced copy for admin focus filters

    # Per-session epoch gauge → session duration & time-of-day.
    add("ai_tx_event_epoch_seconds", ts / 1e9, ts, **base)

    if ev.role == "assistant":
        mbase = dict(base, model=ev.model)
        if ev.usage and not ev.usage.is_empty():
            u = ev.usage
            for kind, val in (("input", u.input), ("output", u.output),
                              ("cache_read", u.cache_read), ("cache_write", u.cache_write)):
                if val:
                    add("ai_tx_tokens", val, ts, kind=kind, **mbase)
            add("ai_tx_cost_usd", pricing.cost_usd(ev.provider, ev.model, u), ts, **mbase)
            for kind, c in pricing.cost_by_kind(ev.provider, ev.model, u).items():
                if c:
                    add("ai_tx_cost_usd_by_kind", c, ts, kind=kind, **mbase)
        if ev.stop_reason:
            add("ai_tx_stop_reason", 1, ts, stop_reason=ev.stop_reason, **base)
        counts: dict[str, int] = {}
        for call in ev.tool_calls:
            counts[call.name] = counts.get(call.name, 0) + 1
            if call.tool_use_id:
                tool_use_times[call.tool_use_id] = ts
        for name, n in counts.items():
            add("ai_tx_tool_calls", n, ts, tool_name=name, **base)

    elif ev.role == "user":
        for res in ev.tool_results:
            use_ts = tool_use_times.get(res.tool_use_id)
            if res.is_error:
                add("ai_tx_tool_errors", 1, ts, **base)
            if use_ts is not None and ts >= use_ts:
                add("ai_tx_tool_latency_seconds", (ts - use_ts) / 1e9, ts, **base)
        if ev.is_human_turn:
            add("ai_tx_turns", 1, ts, **base)
