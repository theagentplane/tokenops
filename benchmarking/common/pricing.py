"""Toy pricing for offline-style micros (live uses live_pricing)."""

from __future__ import annotations

from tokenops.control.core import Usage
from tokenops.control.ledger import PriceFn

_BENCH_MODELS = frozenset({"gpt-4o-mini", "claude-sonnet-4-6"})


def benchmark_price(provider: str, model: str, usage: Usage) -> int:
    if model not in _BENCH_MODELS:
        raise ValueError(f"unknown model {model!r}")
    return usage.input * 10 + usage.output * 30
