"""concurrency_cap — infra shield, NOT a cost lever.

LLD row:
    Detect: inflight(seg) ≥ max_concurrent
    Fix:    Single process → QUEUE in a bounded semaphore (backpressure).
            Serverless/distributed → REJECT with a retryable 429 so the caller's backoff
            resubmits. Never hold an open request across a scalable container; never kill
            admitted work (that wastes tokens for no saving).

This protects memory and downstream rate limits — it does not save tokens. Admitted work
is never cancelled; we only refuse to *start* more.
"""

from __future__ import annotations

from typing import Literal

from tokenops.control.core import (
    Action,
    ActionKind,
    CallRequest,
    Detector,
    LedgerView,
    Policy,
    Severity,
    Signal,
)
from tokenops.control.ledger import Dimension, segment_key_for

Mode = Literal["queue", "reject"]


class ConcurrencyCapDetector(Detector):
    """TRIP when in-flight calls for the scoped segment have reached the ceiling."""

    name = "concurrency_cap"

    def __init__(
        self, max_concurrent: int, dimension: Dimension = "run", tag_key: str | None = None
    ) -> None:
        self.max_concurrent = max_concurrent
        self.dimension = dimension
        self.tag_key = tag_key

    def pre_call(self, request: CallRequest, view: LedgerView) -> Signal | None:
        sk = segment_key_for(request.attr, self.dimension, self.tag_key)
        if sk is None:
            return None
        n = view.inflight(sk)
        if n >= self.max_concurrent:
            return Signal(
                detector=self.name,
                severity=Severity.TRIP,
                run_id=request.attr.run_id,
                reason=f"inflight {n} ≥ max_concurrent {self.max_concurrent} on {sk}",
                evidence={"inflight": n, "max": self.max_concurrent, "segment": sk},
            )
        return None


class ConcurrencyCapPolicy(Policy):
    """QUEUE (single process) or REJECT/429 (distributed). Both are backpressure, never a
    kill — the admitted calls keep running."""

    name = "concurrency_cap"

    def __init__(self, mode: Mode = "reject", retry_after_s: float = 1.0) -> None:
        self.mode = mode
        self.retry_after_s = retry_after_s

    def decide(self, signal: Signal, view: LedgerView) -> Action:
        if self.mode == "queue":
            return Action(
                kind=ActionKind.QUEUE,
                run_id=signal.run_id,
                reason=signal.reason,
                retry_after_s=self.retry_after_s,
            )
        return Action(
            kind=ActionKind.REJECT,
            run_id=signal.run_id,
            reason=signal.reason,
            retry_after_s=self.retry_after_s,
        )


def build(
    max_concurrent: int,
    *,
    dimension: Dimension = "run",
    tag_key: str | None = None,
    mode: Mode = "reject",
    retry_after_s: float = 1.0,
) -> tuple[Detector, Policy]:
    return (
        ConcurrencyCapDetector(max_concurrent, dimension, tag_key),
        ConcurrencyCapPolicy(mode, retry_after_s),
    )
