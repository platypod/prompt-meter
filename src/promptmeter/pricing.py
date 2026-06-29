"""Per-provider, per-model token rates → notional USD cost.

Costs are **notional API-equivalent** (tokens × list price), not anyone's actual
subscription bill. Update the tables when pricing changes. Unknown models fall
back to the provider's default tier.

Rates are USD per 1M tokens: (input, output). Cache read is billed at 0.1×
input, a 5-minute cache write at 1.25× input, a 1-hour write at 2× input.
"""
from __future__ import annotations

from .events import Usage

# provider -> { model_substring: (input_per_mtok, output_per_mtok) }
RATES: dict[str, dict[str, tuple[float, float]]] = {
    "claude-code": {
        "opus": (15.0, 75.0),
        "sonnet": (3.0, 15.0),
        "haiku": (0.80, 4.0),
        "__default__": (15.0, 75.0),  # opus-tier fallback
    },
    # copilot / hermes rate tables go here as those providers land.
}

CACHE_READ_MULT = 0.10
CACHE_WRITE_MULT = 1.25  # 5-minute write; 1h ≈ 2× — folded into cache_write upstream


def _rate(provider: str, model: str) -> tuple[float, float]:
    table = RATES.get(provider, {})
    for key, rate in table.items():
        if key != "__default__" and key in model:
            return rate
    return table.get("__default__", (0.0, 0.0))


def cost_usd(provider: str, model: str, usage: Usage) -> float:
    inp, out = _rate(provider, model)
    return (
        usage.input * inp
        + usage.output * out
        + usage.cache_read * inp * CACHE_READ_MULT
        + usage.cache_write * inp * CACHE_WRITE_MULT
    ) / 1_000_000.0


def cost_by_kind(provider: str, model: str, usage: Usage) -> dict[str, float]:
    inp, out = _rate(provider, model)
    return {
        "input": usage.input * inp / 1e6,
        "output": usage.output * out / 1e6,
        "cache_read": usage.cache_read * inp * CACHE_READ_MULT / 1e6,
        "cache_write": usage.cache_write * inp * CACHE_WRITE_MULT / 1e6,
    }
