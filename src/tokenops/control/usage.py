"""Normalize provider counts once into independently priceable Usage buckets.

SDK totals include details, except native Anthropic input which excludes cache reads.
Flat dispatch/agent-step counts always use inclusive input/output totals.
Cache creation pricing remains a separate follow-up.
"""

from __future__ import annotations

from tokenops.control.core import Usage


def _count(obj: object, primary: str, fallback: str = "") -> int:
    value = getattr(obj, primary, None)
    if value is None and fallback:
        value = getattr(obj, fallback, None)
    return int(value or 0)


def usage_from_counts(counts: object, *, native: bool = False) -> Usage:
    """Read SDK usage (native=True) or the inclusive flat dispatch/step contract."""
    input_tokens = _count(counts, "prompt_tokens", "input_tokens")
    output_tokens = _count(counts, "completion_tokens", "output_tokens")
    if native and hasattr(counts, "cache_read_input_tokens"):
        # Anthropic input_tokens already excludes cached reads.
        cached = _count(counts, "cache_read_input_tokens")
        reasoning = 0
    else:
        if native:
            input_details = getattr(counts, "prompt_tokens_details", None)
            if input_details is None:
                input_details = getattr(counts, "input_tokens_details", None)
            output_details = getattr(counts, "completion_tokens_details", None)
            if output_details is None:
                output_details = getattr(counts, "output_tokens_details", None)
            cached = _count(input_details, "cached_tokens")
            reasoning = _count(output_details, "reasoning_tokens")
        else:
            cached = _count(counts, "cached_tokens")
            reasoning = _count(counts, "reasoning_tokens")
        input_tokens -= cached
        output_tokens -= reasoning
    return Usage(input=input_tokens, output=output_tokens, cached=cached, reasoning=reasoning)
