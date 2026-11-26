"""pricing.build_price_book — micro-USD integer pricing, fail closed."""

from __future__ import annotations

import pytest

from tokenops.framework.core import Usage
from tokenops.framework.pricing import DEFAULT_RATES, Rate, build_price_book


def test_prices_known_model_in_micros():
    price = build_price_book()
    # 1M input tokens of gpt-4o-mini @ 150_000 micros/1M == $0.15 == 150_000 micros
    assert price("openai", "gpt-4o-mini", Usage(input=1_000_000)) == 150_000
    # mixed: 820 in + 45 out → (820*150000 + 45*600000)//1e6
    expected = (820 * 150_000 + 45 * 600_000) // 1_000_000
    assert price("openai", "gpt-4o-mini", Usage(input=820, output=45)) == expected


def test_cached_cheaper_than_input():
    price = build_price_book()
    full = price("openai", "gpt-4o-mini", Usage(input=1_000_000))
    cached = price("openai", "gpt-4o-mini", Usage(cached=1_000_000))
    assert 0 < cached < full  # cached defaults to half the input rate


def test_fails_closed_on_unknown_model():
    price = build_price_book()
    with pytest.raises(ValueError, match="no price"):
        price("openai", "mystery-model", Usage(input=1))


def test_custom_rate_table():
    price = build_price_book({"flat": Rate(input=1_000_000, output=1_000_000)})
    assert price("x", "flat", Usage(input=1, output=1)) == 2  # 2 tokens @ 1 micro each


def test_claude_rates_match_anthropic_list_prices():
    price = build_price_book()
    assert price("anthropic", "claude-opus-5-5", Usage(input=1_000_000)) == 4_000_000
    assert price("anthropic", "claude-opus-5-5", Usage(output=1_000_000)) == 20_000_000
    assert price("anthropic", "claude-opus-5-5", Usage(cached=1_000_000)) == 200_000
    assert price("anthropic", "claude-opus-4-8", Usage(input=1_000_000)) == 5_000_000


def test_every_claude_rate_sets_its_cache_read_price():
    # The input // 2 default fits OpenAI, not Anthropic (cache reads are 2.5% to 10% of input).
    claude = {m: r for m, r in DEFAULT_RATES.items() if m.startswith("claude-")}
    assert claude and all(
        r.cached is not None and r.cached <= r.input // 10 for r in claude.values()
    )
