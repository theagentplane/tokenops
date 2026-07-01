"""pre_call_worst_case — default, preventive ceiling. Stops a breach *before* spend.

LLD row:
    Detect: spent(run) + price(est_in) + price(max(out, default)) ≥ budget
    Fix:    MUTATE — set max_output to the default cap if unset (priced cap = enforced
            cap), then HALT before dispatch if it would still breach. Unknown price fails
            closed; never price the model's physical max.

Where cost_budget is the *guarantee* (trips on actual spend, after the fact),
pre_call_worst_case is the *prevention* (refuses the call whose worst case cannot fit).
The two are complementary: prevention keeps you from breaching; the guarantee ensures you
never stay breached.

Two-step fix encoded as two severities:
    TRIP  → even with a bounded output cap, worst case ≥ budget → HALT.
    WARN  → fits, but the call had no output cap → MUTATE to set the default cap, so the
            number we *priced* is the number that is actually *enforced*.
"""

from __future__ import annotations

from tokenops.control.core import (
    Action,
    ActionKind,
    CallRequest,
    Detector,
    LedgerView,
    Policy,
    Severity,
    Signal,
    Usage,
)
from tokenops.control.ledger import Budget, PriceFn, segment_key

#: Default output cap applied when a call leaves ``max_output_tokens`` unset. A priced cap
#: must be an *enforced* cap, so we never price the model's physical maximum.
DEFAULT_MAX_OUTPUT = 1024


class PreCallWorstCaseDetector(Detector):
    """Project the call's worst case against the remaining budget, before dispatch."""

    name = "pre_call_worst_case"

    def __init__(self, budget: Budget, price: PriceFn, default_max_output: int = DEFAULT_MAX_OUTPUT) -> None:
        self.budget = budget
        self._price = price
        self.default_max_output = default_max_output

    def pre_call(self, request: CallRequest, view: LedgerView) -> Signal | None:
        sk = segment_key(request.attr, self.budget)
        if sk is None:
            return None
        left = view.budget_left(self.budget.budget_id, sk, self.budget.period)

        capped_out = (
            request.max_output_tokens
            if request.max_output_tokens is not None
            else self.default_max_output
        )
        try:
            projected = (
                self._price(request.provider, request.model, Usage(input=request.estimated_input_tokens))
                + self._price(request.provider, request.model, Usage(output=capped_out))
            )
        except Exception as exc:  # unknown price → fail closed (HALT), never assume 0
            return Signal(
                detector=self.name, severity=Severity.TRIP, run_id=request.attr.run_id,
                reason=f"unknown price for {request.provider}/{request.model}; failing closed ({exc})",
                evidence={"fail_closed": True},
            )

        if projected >= left:
            return Signal(
                detector=self.name, severity=Severity.TRIP, run_id=request.attr.run_id,
                reason=f"worst-case {projected} ≥ remaining budget {left} (micros)",
                evidence={"projected": projected, "left": left, "capped_out": capped_out},
            )
        if request.max_output_tokens is None:
            return Signal(
                detector=self.name, severity=Severity.WARN, run_id=request.attr.run_id,
                reason=f"output cap unset; bounding to {self.default_max_output} so priced cap == enforced cap",
                evidence={"set_cap": self.default_max_output, "projected": projected, "left": left},
            )
        return None


class PreCallWorstCasePolicy(Policy):
    name = "pre_call_worst_case"

    def decide(self, signal: Signal, view: LedgerView) -> Action:
        if signal.severity is Severity.TRIP:
            return Action(kind=ActionKind.HALT, run_id=signal.run_id, reason=signal.reason)
        # WARN → bound the output so the worst case we priced is the one enforced.
        cap = int(signal.evidence.get("set_cap", DEFAULT_MAX_OUTPUT))
        return Action(
            kind=ActionKind.MUTATE, run_id=signal.run_id, reason=signal.reason,
            max_output_tokens=cap,
        )


def build(budget: Budget, price: PriceFn, default_max_output: int = DEFAULT_MAX_OUTPUT) -> tuple[Detector, Policy]:
    return PreCallWorstCaseDetector(budget, price, default_max_output), PreCallWorstCasePolicy()
