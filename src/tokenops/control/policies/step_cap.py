"""step_cap — optional / opt-in. A step-count ceiling per run.

LLD row:
    Detect: steps(run) ≥ max_steps   (per recorded event; per run, not per period)
    Fix:    HALT. Good for predictable-trajectory workflows; in A2A the shared run sums
            both agents' steps.

Not a default — step count is task-dependent, and budget is the universal backstop. Opt
in when a workflow has a known, bounded trajectory and you want a cheap circuit breaker
that does not depend on pricing.
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


class StepCapDetector(Detector):
    """TRIP when the run's recorded step count reaches the cap."""

    name = "step_cap"

    def __init__(self, max_steps: int) -> None:
        self.max_steps = max_steps

    def observe(self, attr: Attribution, step: BoundaryStep, view: LedgerView) -> Signal | None:
        # step.step is the monotonic per-run count == view.step_count at this moment.
        if step.step >= self.max_steps:
            return Signal(
                detector=self.name,
                severity=Severity.TRIP,
                run_id=attr.run_id,
                reason=f"step cap reached: {step.step} >= {self.max_steps}",
                evidence={"steps": step.step, "max_steps": self.max_steps},
            )
        return None


class StepCapPolicy(Policy):
    name = "step_cap"

    def decide(self, signal: Signal, view: LedgerView) -> Action:
        return Action(kind=ActionKind.HALT, run_id=signal.run_id, reason=signal.reason)


def build(max_steps: int) -> tuple[Detector, Policy]:
    return StepCapDetector(max_steps), StepCapPolicy()
