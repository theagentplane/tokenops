"""scripts/check-claude-prices.py: parse the pricing page table and compare it with the price book."""

from __future__ import annotations

import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("check", ROOT / "scripts" / "check-claude-prices.py")
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)

PAGE = """
| Model | Base input tokens | 5m cache writes | 1h cache writes | Cache hits and refreshes | Output tokens |
| :---- | :---- | :---- | :---- | :---- | :---- |
| Claude Opus 5.5 | $4 / MTok | $5 / MTok | $8 / MTok | $0.20 / MTok<sup>2</sup> | $20 / MTok |
| Claude Mythos 5.2 ([limited availability](https://example.com/a)) | $8 / MTok | $10 / MTok | $16 / MTok | $0.20 / MTok | $40 / MTok |
| Claude Haiku 5.5 (for prompts up to 100,000 tokens) | $0.10 / MTok | $0.125 / MTok | $0.20 / MTok | $0.01 / MTok | $0.50 / MTok |
| Claude Haiku 5.5 (for prompts over 100,000 tokens) | $0.50 / MTok | $0.625 / MTok | $1 / MTok | $0.05 / MTok | $2.50 / MTok |
| Claude Opus 4 ([retired](https://example.com/b)) | $15 / MTok | $18.75 / MTok | $30 / MTok | $1.50 / MTok | $75 / MTok |

Next section.
"""


def test_reads_the_table_skipping_retired_models_and_long_prompt_tiers():
    page = check.published(PAGE)
    assert set(page) == {"claude-opus-5-5", "claude-mythos-5-2", "claude-haiku-5-5"}
    assert page["claude-opus-5-5"] == {
        "input": 4.0,
        "write_5m": 5.0,
        "write_1h": 8.0,
        "cache_read": 0.2,
        "output": 20.0,
    }
    assert page["claude-haiku-5-5"]["input"] == 0.10


def test_price_book_matches_and_differences_are_reported():
    mine, w5m, w1h = check.ours()
    page = {m: v for m, v in check.published(PAGE).items() if m in mine}
    assert check.compare({m: mine[m] for m in page}, w5m, w1h, page) == []

    changed = {"claude-opus-5-5": {**page["claude-opus-5-5"], "output": 25.0}}
    problems = check.compare({"claude-opus-5-5": mine["claude-opus-5-5"]}, w5m, w1h, changed)
    assert problems == ["- `claude-opus-5-5` output: page $25, ours $20 per MTok."]
    assert "not in `DEFAULT_RATES`" in check.compare({}, w5m, w1h, page)[0]
