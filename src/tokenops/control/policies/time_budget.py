"""time_budget -- optional / opt-in. A wall-clock ceiling per run.

LLD row:
    Detect: elapsed(run) >= max_seconds   (observe moment; per run)
    Fix:    HALT. Good for workflows whose cost is latency rather than tokens.

Not a default -- elapsed time is task-dependent. Opt in when a workflow has a
known time bound and you want a cheap circuit breaker independent of pricing.
"""

from __future__ import annotations

from tokenops.control.core import (
    Action,
    ActionKind,
    Attribution,
    BoundaryStep,
    Detector,
    LedgerView,
    Policy,
    Severity,
    Signal,
)


class TimeBudgetDetector(Detector):
    """TRIP when the run's wall-clock age reaches the ceiling."""

    name = "time_budget"

    def __init__(self, max_seconds: float) -> None:
        self.max_seconds = max_seconds
        self._started: dict[str, float] = {}

    def observe(self, attr: Attribution, step: BoundaryStep, view: LedgerView) -> Signal | None:
        start = self._started.setdefault(attr.trace_id, step.ts)
        elapsed = step.ts - start
        if elapsed >= self.max_seconds:
            return Signal(
                detector=self.name,
                severity=Severity.TRIP,
                trace_id=attr.trace_id,
                reason=f"time budget exceeded: {elapsed:.1f}s >= {self.max_seconds}s",
                evidence={"elapsed_s": elapsed, "max_seconds": self.max_seconds},
            )
        return None


class TimeBudgetPolicy(Policy):
    name = "time_budget"

    def decide(self, signal: Signal, view: LedgerView) -> Action:
        return Action(kind=ActionKind.HALT, trace_id=signal.trace_id, reason=signal.reason)


def build(max_seconds: float) -> tuple[Detector, Policy]:
    return TimeBudgetDetector(max_seconds), TimeBudgetPolicy()
