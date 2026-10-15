"""Ledger events in the control plane's 1.0 wire shape.

There are no step events and no idempotency key (control-plane ADR 0007 / 0009).
"""

from __future__ import annotations

from typing import Literal

from tokenops.framework.core import Micros
from tokenops.framework.ledger_types import BudgetTarget, LedgerEvent

__all__ = ["halt_event", "inflight_event", "spent_add_event"]


def inflight_event(
    kind: Literal["admit", "complete"], trace_id: str, segment_key: str
) -> LedgerEvent:
    return {"kind": kind, "trace_id": trace_id, "segment_key": segment_key}


def halt_event(
    kind: Literal["halt_mark", "halt_clear"], trace_id: str, reason: str = ""
) -> LedgerEvent:
    event: LedgerEvent = {"kind": kind, "trace_id": trace_id}
    if reason:
        event["reason"] = reason
    return event


def spent_add_event(trace_id: str, delta: Micros, targets: list[BudgetTarget]) -> LedgerEvent:
    return {
        "kind": "spent_add",
        "trace_id": trace_id,
        "delta_micros": delta,
        "targets": targets,
    }
