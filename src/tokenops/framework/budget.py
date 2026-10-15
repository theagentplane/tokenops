"""Budgets and segment keys: what a spend limit is and which accumulator an event feeds.

A :class:`Budget` is a limit bound to one attribution dimension; a segment key is the string
that names the accumulator an event is charged to (``trace:<id>``, ``user:<id>``, ...).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from tokenops.framework.core import Attribution, Micros

__all__ = [
    "LIFETIME",
    "TRACE_TOTAL_BUDGET",
    "UNLIMITED_LEFT",
    "Budget",
    "Dimension",
    "PriceFn",
    "segment_key",
    "segment_key_for",
    "trace_id_from_segment_key",
]

#: Resolve a call's price. Injected (the Instrument module owns the price book). Must
#: fail closed: an unknown (provider, model) raises rather than returning 0.
PriceFn = Callable[[str, str, "object"], Micros]

Dimension = Literal["trace", "user", "agent", "tenant", "tag"]

#: Period label for the run-total accumulator and v1 budgets (whole-run / lifetime).
LIFETIME = "lifetime"

#: A budget_left answer for an unlimited (``limit_micros is None``) accumulator. Large
#: enough that no worst-case projection treats it as exhausted; never enforced against.
UNLIMITED_LEFT: Micros = 1 << 62


# =========================================================================== #
# Budget — a limit bound to a segment matcher (config template instantiates these)
# =========================================================================== #


@dataclass(frozen=True, kw_only=True)
class Budget:
    """A spend limit attached to one segment dimension.

    ``limit_micros = None`` means *unlimited* — a pure accumulator that totals spend but
    never trips. The system run-total budget is the canonical example: it exists so the
    run total has one home in the ``spent`` map, not to cap anything.

    ``dimension`` picks which Attribution field forms the segment key; ``tag_key`` names
    the tag when ``dimension == "tag"``. ``period`` labels the accumulator bucket
    ("lifetime" for v1; monthly/daily bucketing is a future refinement of the key).
    """

    budget_id: str
    limit_micros: Micros | None
    dimension: Dimension = "trace"
    tag_key: str | None = None
    period: str = "lifetime"


#: The canonical run-total accumulator (Design A). Always present, unlimited, run-scoped —
#: so the run total has exactly one home in ``spent`` and every run is covered by one
#: definition. Never enforced against; ``cost_micros`` and ``cum_spent_micros`` read it.
TRACE_TOTAL_BUDGET = Budget(
    budget_id="__trace_total__", limit_micros=None, dimension="trace", period=LIFETIME
)


def segment_key_for(
    attr: Attribution, dimension: Dimension, tag_key: str | None = None
) -> str | None:
    """Resolve the segment key for a dimension. The shared primitive any policy (budget or
    not — e.g. concurrency_cap) uses to scope itself.

    Returns ``None`` when the attribution does not carry the dimension (e.g. a tenant scope
    on an event with no tenant) — that event simply does not match.
    """
    if dimension == "trace":
        return f"trace:{attr.trace_id}"
    if dimension == "user":
        return f"user:{attr.user}"
    if dimension == "agent":
        return f"agent:{attr.agent}"
    if dimension == "tenant":
        return f"tenant:{attr.tenant}" if attr.tenant else None
    if dimension == "tag":
        if tag_key and tag_key in attr.tags:
            return f"tag:{tag_key}={attr.tags[tag_key]}"
        return None
    return None


def segment_key(attr: Attribution, budget: Budget) -> str | None:
    """Resolve the segment key this *budget* matches — thin wrapper over ``segment_key_for``."""
    return segment_key_for(attr, budget.dimension, budget.tag_key)


def trace_id_from_segment_key(segment_key: str) -> str | None:
    """Recover ``trace_id`` from a ``trace:``-dimension segment key. ``None`` for any other
    dimension (user/agent/tenant/tag) — those don't carry a trace_id at all.

    The plane's ``precheck`` only *uses* ``trace_id`` to answer ``halt`` — a ``spent`` or
    ``inflight`` lookup for a non-trace segment is valid with an empty ``trace_id``, so
    callers pass ``""`` when this returns ``None``.
    """
    prefix = "trace:"
    return segment_key[len(prefix) :] if segment_key.startswith(prefix) else None
