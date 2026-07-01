"""Per-provider, per-model token rates → notional USD cost.

Costs are **notional API-equivalent** (tokens × list price), not anyone's actual
subscription bill. Update the tables when pricing changes. Unknown models fall
back to the provider's default tier.

Rates are USD per 1M tokens: (input, output). Cache read is billed at 0.1×
input; a 5-minute cache write at 1.25× input; a 1-hour write at 2× input.
"""
from __future__ import annotations

from .events import Usage

# provider -> { model_prefix: (input_per_mtok, output_per_mtok) }
# Matched by model.startswith(prefix), most-specific-first (dict iteration
# order), so e.g. "claude-opus-4-8" doesn't fall through to a looser "opus"
# bucket priced for a different generation.
RATES: dict[str, dict[str, tuple[float, float]]] = {
    "claude-code": {
        "claude-fable-5": (10.0, 50.0),
        "claude-mythos-5": (10.0, 50.0),
        "claude-opus-4-8": (5.0, 25.0),
        "claude-opus-4-7": (5.0, 25.0),
        "claude-opus-4-6": (5.0, 25.0),
        "claude-opus-4-5": (5.0, 25.0),
        "claude-opus-4-1": (15.0, 75.0),
        "claude-opus-4-0": (15.0, 75.0),
        "claude-sonnet-5": (3.0, 15.0),  # assumed same tier as sonnet-4.x
        "claude-sonnet-4-6": (3.0, 15.0),
        "claude-sonnet-4-5": (3.0, 15.0),
        "claude-haiku-4-5": (1.0, 5.0),
        "__default__": (5.0, 25.0),  # unknown model → assume current opus-tier
    },
    # copilot / hermes rate tables go here as those providers land.
}

CACHE_READ_MULT = 0.10
CACHE_WRITE_5M_MULT = 1.25
CACHE_WRITE_1H_MULT = 2.00


def _rate(provider: str, model: str) -> tuple[float, float]:
    table = RATES.get(provider, {})
    for key, rate in table.items():
        if key != "__default__" and model.startswith(key):
            return rate
    return table.get("__default__", (0.0, 0.0))


def cost_usd(provider: str, model: str, usage: Usage) -> float:
    inp, out = _rate(provider, model)
    return (
        usage.input * inp
        + usage.output * out
        + usage.cache_read * inp * CACHE_READ_MULT
        + usage.cache_write_5m * inp * CACHE_WRITE_5M_MULT
        + usage.cache_write_1h * inp * CACHE_WRITE_1H_MULT
    ) / 1_000_000.0


def cost_by_kind(provider: str, model: str, usage: Usage) -> dict[str, float]:
    inp, out = _rate(provider, model)
    return {
        "input": usage.input * inp / 1e6,
        "output": usage.output * out / 1e6,
        "cache_read": usage.cache_read * inp * CACHE_READ_MULT / 1e6,
        "cache_write": (
            usage.cache_write_5m * CACHE_WRITE_5M_MULT
            + usage.cache_write_1h * CACHE_WRITE_1H_MULT
        ) * inp / 1e6,
    }
