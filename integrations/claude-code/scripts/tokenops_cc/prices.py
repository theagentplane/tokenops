"""Claude prices (USD per million tokens) and the cost of one response's usage.

Rates come from ``prices.json``, generated from ``tokenops.framework.pricing`` by
``scripts/sync-claude-prices.py`` (one price source, ADR 0009). Cache writes are priced as a
multiple of the input rate; fast mode bills 2x. Unknown models are priced at Opus 5.5 rates and
flagged, so a report never silently shows $0.
"""

from __future__ import annotations

import json
from pathlib import Path

_DATA = json.loads((Path(__file__).with_name("prices.json")).read_text(encoding="utf-8"))
PRICES: dict[str, dict[str, float]] = _DATA["models"]
CACHE_WRITE_5M: float = _DATA["cache_write_5m"]
CACHE_WRITE_1H: float = _DATA["cache_write_1h"]
FAST_MULTIPLIER = 2.0
DEFAULT_MODEL = "claude-opus-5-5"


def price_for(model: str) -> tuple[dict[str, float], bool]:
    """(price row, known). Accepts date-suffixed ids such as ``claude-haiku-4-5-20251001``."""
    m = (model or "").strip()
    for key in sorted(PRICES, key=len, reverse=True):
        if m == key or m.startswith(key + "-"):
            return PRICES[key], True
    return PRICES[DEFAULT_MODEL], False


def write_tokens(usage: dict) -> tuple[int, int]:
    """(5-minute, 1-hour) cache-write tokens; untyped writes count as 5-minute."""
    cc = usage.get("cache_creation") or {}
    w1h = cc.get("ephemeral_1h_input_tokens") or 0
    w5m = cc.get("ephemeral_5m_input_tokens")
    if w5m is None:
        w5m = max(0, (usage.get("cache_creation_input_tokens") or 0) - w1h)
    return w5m, w1h


def usage_cost(model: str, usage: dict, speed: str | None = None) -> tuple[float, bool]:
    """Cost in USD of one response's usage block, and whether the model's price was known."""
    p, known = price_for(model)
    w5m, w1h = write_tokens(usage)
    cost = (
        (usage.get("input_tokens") or 0) * p["input"]
        + (usage.get("output_tokens") or 0) * p["output"]
        + (usage.get("cache_read_input_tokens") or 0) * p["cache_read"]
        + (w5m * CACHE_WRITE_5M + w1h * CACHE_WRITE_1H) * p["input"]
    ) / 1e6
    return cost * (FAST_MULTIPLIER if speed == "fast" else 1.0), known
