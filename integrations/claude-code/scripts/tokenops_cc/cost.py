"""Cost breakdown (USD) of a set of responses: by usage type, by model, subagents included."""

from __future__ import annotations

from collections.abc import Iterable

from .prices import CACHE_WRITE_1H, CACHE_WRITE_5M, FAST_MULTIPLIER, price_for, write_tokens
from .transcript import Response


def breakdown(responses: Iterable[Response]) -> dict:
    out: dict = {
        "responses": 0,
        "subagent_responses": 0,
        "cost_usd": 0.0,
        "cost_input": 0.0,
        "cost_output": 0.0,
        "cost_cache_read": 0.0,
        "cost_cache_write": 0.0,
        "by_model": {},
        "unpriced_models": [],
    }
    for r in responses:
        u = r.usage
        p, known = price_for(r.model)
        mult = (FAST_MULTIPLIER if r.speed == "fast" else 1.0) / 1e6
        w5m, w1h = write_tokens(u)
        parts = {
            "cost_input": (u.get("input_tokens") or 0) * p["input"] * mult,
            "cost_output": (u.get("output_tokens") or 0) * p["output"] * mult,
            "cost_cache_read": (u.get("cache_read_input_tokens") or 0) * p["cache_read"] * mult,
            "cost_cache_write": (w5m * CACHE_WRITE_5M + w1h * CACHE_WRITE_1H) * p["input"] * mult,
        }
        cost = sum(parts.values())
        for k, v in parts.items():
            out[k] += v
        out["cost_usd"] += cost
        out["responses"] += 1
        out["subagent_responses"] += int(r.sidechain)
        m = out["by_model"].setdefault(r.model, {"responses": 0, "cost_usd": 0.0})
        m["responses"] += 1
        m["cost_usd"] += cost
        if not known and r.model not in out["unpriced_models"]:
            out["unpriced_models"].append(r.model)
    return out
