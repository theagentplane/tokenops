"""pricing.build_price_book — micro-USD integer pricing, fail closed."""

from __future__ import annotations

import pytest

from tokenops.control.core import Usage
from tokenops.control.pricing import Rate, build_price_book


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
