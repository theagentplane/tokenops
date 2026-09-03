"""cost_guard — POC: instruction-based minimization (not a hard output cap).

LLD row:
    Detect: spent(seg)/limit ≥ 0.8 (edge-triggered) OR velocity from cum_spent_micros over
            last M boundary steps.
    Fix:    If routing: elasticity check, then DOWNGRADE the next call. For minimization,
            INJECT a "keep output minimal" system instruction (and trim input via
            compaction) rather than a hard max_output cap. POC to confirm savings exceed
            the instruction's auxiliary cost.

A hard output cap risks partial output → re-call → more cost, so this nudges instead. The
trigger is **edge-triggered** — fire once when crossing 0.8, not every step after.
"""

from __future__ import annotations

from typing import Literal

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
from tokenops.control.ledger import Budget, segment_key

Mode = Literal["minimize", "downgrade"]


class CostGuardDetector(Detector):
    """Edge-triggered at 0.8 of the budget (or a velocity threshold). Fires once per run."""

    name = "cost_guard"

    def __init__(
        self,
        budget: Budget,
        *,
        threshold: float = 0.8,
        velocity_micros_per_step: int | None = None,
        velocity_m: int = 5,
    ) -> None:
        self.budget = budget
        self.threshold = threshold
        self.velocity_micros_per_step = velocity_micros_per_step
        self.velocity_m = velocity_m
        self._fired: set[str] = set()

    def reset(self, run_id: str) -> None:
        self._fired.discard(run_id)

    def observe(self, attr: Attribution, step: BoundaryStep, view: LedgerView) -> Signal | None:
        if attr.run_id in self._fired or self.budget.limit_micros is None:
            return None
        sk = segment_key(attr, self.budget)
        if sk is None:
            return None
        spent = self.budget.limit_micros - view.budget_left(
            self.budget.budget_id, sk, self.budget.period
        )
        ratio = spent / self.budget.limit_micros
        vel = view.velocity(attr.run_id, self.velocity_m)
        tripped_ratio = ratio >= self.threshold
        tripped_vel = (
            self.velocity_micros_per_step is not None and vel >= self.velocity_micros_per_step
        )
        if tripped_ratio or tripped_vel:
            self._fired.add(attr.run_id)  # edge-trigger: only once
            return Signal(
                detector=self.name,
                severity=Severity.WARN,
                run_id=attr.run_id,
                reason=f"spend at {ratio:.0%} of budget (vel {vel:.0f}/step), minimizing",
                evidence={"ratio": ratio, "velocity": vel},
            )
        return None


class CostGuardPolicy(Policy):
    name = "cost_guard"

    def __init__(self, mode: Mode = "minimize", downgrade_to: str | None = None) -> None:
        self.mode = mode
        self.downgrade_to = downgrade_to

    def decide(self, signal: Signal, view: LedgerView) -> Action:
        if self.mode == "downgrade" and self.downgrade_to:
            # "downgrade" is a model swap — a MUTATE carrying downgrade_to, not its own kind.
            return Action(
                kind=ActionKind.MUTATE,
                run_id=signal.run_id,
                reason=signal.reason,
                downgrade_to=self.downgrade_to,
            )
        return Action(
            kind=ActionKind.INJECT,
            run_id=signal.run_id,
            reason=signal.reason,
            inject_message="BUDGET PRESSURE: keep responses minimal and to the point; omit "
            "preamble and restatement until the task is complete.",
        )


def build(
    budget: Budget,
    *,
    threshold: float = 0.8,
    mode: Mode = "minimize",
    downgrade_to: str | None = None,
    velocity_micros_per_step: int | None = None,
    velocity_m: int = 5,
) -> tuple[Detector, Policy]:
    return (
        CostGuardDetector(
            budget,
            threshold=threshold,
            velocity_micros_per_step=velocity_micros_per_step,
            velocity_m=velocity_m,
        ),
        CostGuardPolicy(mode, downgrade_to),
    )
