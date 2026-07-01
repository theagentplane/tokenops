"""cost_budget — the guarantee. Default, always-on.

LLD row:
    Detect: ∃ budget B: spent(seg_B) ≥ limit_B   (local check vs the leased slice)
    Fix:    HALT — raise Halt, set the halted flag; the IN connector refuses every later
            call. Roll child cost into the parent first. Idempotent.

This is the universal backstop. ``pre_call_worst_case`` prevents the breach; this one
*guarantees* it can never be exceeded for long — it trips at ``observe`` on actual spend,
the moment an accumulator crosses its limit.

The detector reads the SAME ``Budget`` the ledger accumulates (matched by ``budget_id``),
so detection and accounting can never disagree — both read one accumulator.
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
from tokenops.control.ledger import Budget, segment_key


class CostBudgetDetector(Detector):
    """TRIP when this budget's accumulator for the call's segment is exhausted."""

    name = "cost_budget"

    def __init__(self, budget: Budget) -> None:
        self.budget = budget

    def observe(self, attr: Attribution, step: BoundaryStep, view: LedgerView) -> Signal | None:
        sk = segment_key(attr, self.budget)
        if sk is None:
            return None  # this event does not feed this budget's segment
        left = view.budget_left(self.budget.budget_id, sk, self.budget.period)
        if left <= 0:
            return Signal(
                detector=self.name,
                severity=Severity.TRIP,
                run_id=attr.run_id,
                reason=f"budget '{self.budget.budget_id}' exhausted on {sk} ({left} micros left)",
                evidence={"budget_id": self.budget.budget_id, "segment": sk, "left_micros": left},
            )
        return None


class CostBudgetPolicy(Policy):
    """Any TRIP from cost_budget is preventive — HALT. (Roll-up into the parent already
    happened at ``record`` time, so the halted run's total reflects the whole run.)"""

    name = "cost_budget"

    def decide(self, signal: Signal, view: LedgerView) -> Action:
        return Action(kind=ActionKind.HALT, run_id=signal.run_id, reason=signal.reason)


def build(budget: Budget) -> tuple[Detector, Policy]:
    """Instantiate the cost_budget template for one budget."""
    return CostBudgetDetector(budget), CostBudgetPolicy()
