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


#: Approximate list prices (micros per 1M tokens). Swap for exact rates anytime.
DEFAULT_RATES: dict[str, Rate] = {
    "gpt-4o-mini": Rate(input=150_000, output=600_000),
    "gpt-4o": Rate(input=2_500_000, output=10_000_000),
    "claude-sonnet-4-6": Rate(input=3_000_000, output=15_000_000),
    "claude-haiku-4-5": Rate(input=800_000, output=4_000_000),
    "claude-opus-4-8": Rate(input=15_000_000, output=75_000_000),
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
