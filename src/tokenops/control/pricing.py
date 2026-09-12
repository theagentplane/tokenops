"""Pricing — the production price book (Instrument's price half).

Promotes the tests' ``toy_price`` to a real, per-model rate table. Rates are
**approximate** (rough public list prices) and easy to swap; what matters for the control
plane is that every live ``Governor`` has a ``PriceFn`` that:

  * prices in **micro-USD integers** (``$1.00 == 1_000_000``), so no float drift;
  * accounts for the hidden categories (``cached`` cheaper input, ``reasoning`` like output);
  * **fails closed** on an unknown model (raises) — it never silently returns 0.

Rates are stored as **micros per 1,000,000 tokens** (so ``$0.15 / 1M tokens`` = ``150_000``).
"""

from __future__ import annotations

from dataclasses import dataclass

from tokenops.control.core import Micros, Usage
from tokenops.control.ledger import PriceFn

_PER_MILLION = 1_000_000


@dataclass(frozen=True)
class Rate:
    """micros per 1,000,000 tokens. ``cached`` defaults to half the input rate; ``reasoning``
    defaults to the output rate."""

    input: int
    output: int
    cached: int | None = None
    reasoning: int | None = None


#: Public list prices as micros per 1M tokens, current as of 2026-09-12.
#: Grouped by provider; each group is also exposed under its ``provider/`` prefix
#: below, so both ``gpt-4o`` and ``openai/gpt-4o`` resolve.
_ANTHROPIC: dict[str, Rate] = {
    "claude-opus-5": Rate(input=5_000_000, output=25_000_000, cached=500_000),
    "claude-sonnet-5": Rate(input=2_000_000, output=10_000_000, cached=200_000),
    "claude-opus-4-8": Rate(input=5_000_000, output=25_000_000, cached=500_000),
    "claude-opus-4-6": Rate(input=5_000_000, output=25_000_000, cached=500_000),
    "claude-sonnet-4-6": Rate(input=3_000_000, output=15_000_000, cached=300_000),
    "claude-sonnet-4-5": Rate(input=3_000_000, output=15_000_000, cached=300_000),
    "claude-haiku-4-5": Rate(input=1_000_000, output=5_000_000, cached=100_000),
    "claude-opus-4-1": Rate(input=15_000_000, output=75_000_000, cached=1_500_000),
}

_OPENAI: dict[str, Rate] = {
    "gpt-5.4": Rate(input=2_500_000, output=15_000_000, cached=250_000),
    "gpt-5.4-mini": Rate(input=750_000, output=4_500_000, cached=75_000),
    "gpt-5.2": Rate(input=1_750_000, output=14_000_000, cached=175_000),
    "gpt-5.1": Rate(input=1_250_000, output=10_000_000, cached=125_000),
    "gpt-5": Rate(input=1_250_000, output=10_000_000, cached=125_000),
    "gpt-5-mini": Rate(input=250_000, output=2_000_000, cached=25_000),
    "gpt-5-nano": Rate(input=50_000, output=400_000, cached=5_000),
    "gpt-4.1": Rate(input=2_000_000, output=8_000_000, cached=500_000),
    "gpt-4.1-mini": Rate(input=400_000, output=1_600_000, cached=100_000),
    "gpt-4o": Rate(input=2_500_000, output=10_000_000, cached=1_250_000),
    "gpt-4o-mini": Rate(input=150_000, output=600_000, cached=75_000),
}

_GEMINI: dict[str, Rate] = {
    "gemini-3.8-flash": Rate(input=750_000, output=3_750_000, cached=75_000),
    "gemini-3.7-flash": Rate(input=750_000, output=3_750_000, cached=75_000),
    "gemini-3.5-flash": Rate(input=1_500_000, output=9_000_000, cached=150_000),
    "gemini-3.5-flash-lite": Rate(input=300_000, output=2_500_000, cached=30_000),
    "gemini-3-pro-preview": Rate(input=2_000_000, output=12_000_000, cached=200_000),
    "gemini-3-flash-preview": Rate(input=500_000, output=3_000_000, cached=50_000),
    "gemini-2.5-pro": Rate(input=1_250_000, output=10_000_000, cached=125_000),
    "gemini-2.5-flash": Rate(input=300_000, output=2_500_000, cached=30_000),
}


def _with_prefix(provider: str, rates: dict[str, Rate]) -> dict[str, Rate]:
    """Expose each model under both its bare name and ``provider/name``."""
    return {**rates, **{f"{provider}/{name}": rate for name, rate in rates.items()}}


DEFAULT_RATES: dict[str, Rate] = {
    **_with_prefix("anthropic", _ANTHROPIC),
    **_with_prefix("openai", _OPENAI),
    **_with_prefix("gemini", _GEMINI),
}


def build_price_book(rates: dict[str, Rate] | None = None) -> PriceFn:
    """Return a ``PriceFn`` ``(provider, model, usage) -> micros`` over a rate table.

    Fail closed: an unknown model raises ``ValueError`` rather than returning 0.
    """
    table = dict(DEFAULT_RATES if rates is None else rates)

    def price(provider: str, model: str, usage: object) -> Micros:
        if not isinstance(usage, Usage):
            raise TypeError(f"expected Usage, got {type(usage)!r}")
        rate = table.get(model)
        if rate is None:
            raise ValueError(
                f"no price for model {model!r} (provider {provider!r}); failing closed"
            )
        cached_rate = rate.cached if rate.cached is not None else rate.input // 2
        reasoning_rate = rate.reasoning if rate.reasoning is not None else rate.output
        total = (
            usage.input * rate.input
            + usage.output * rate.output
            + usage.cached * cached_rate
            + usage.reasoning * reasoning_rate
        )
        return total // _PER_MILLION

    return price
