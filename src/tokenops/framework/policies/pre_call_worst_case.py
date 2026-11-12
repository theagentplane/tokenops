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

**Cap per kind of call** (``caps_by_kind``, off by default): an adapter that labels calls
(``CallRequest.tags["call_kind"]``) can give each kind its own default cap, for example
``{"plan": 2048, "extract": 512}`` for a browser agent whose page-extraction calls answer in
about 100 tokens. A runaway call spends its whole cap, so a smaller cap where the output is
known to be small makes a runaway cheaper. Unlabelled calls, and kinds not in the map, use
``default_max_output``.

**Wrap-up near the end of the budget** (``wrap_up``, off by default): when the remaining
budget fits this call's worst case but not two of them, this call is the last one that can
run, so it carries one "budget almost spent, finish now with your best answer" message
(MUTATE, with the cap as usual). ``wrap_up_reserve`` (default 1) is how many worst-case calls
may still fit when the message is sent: an agent that needs one more step before it can write
its answer needs 2 (browser-use clicked once more in both budget halts with a reserve of 1). The next call that does not fit is halted exactly as
without it, so the budget is never exceeded.

Two-step fix encoded as two severities:
    TRIP  → even with a bounded output cap, worst case ≥ budget → HALT.
    WARN  → fits, but the call had no output cap → MUTATE to set the default cap, so the
            number we *priced* is the number that is actually *enforced*.
"""

from __future__ import annotations

from collections.abc import Mapping

from tokenops.framework.core import (
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
from tokenops.framework.ledger import Budget, PriceFn, segment_key

#: Default output cap applied when a call leaves ``max_output_tokens`` unset. A priced cap
#: must be an *enforced* cap, so we never price the model's physical maximum.
DEFAULT_MAX_OUTPUT = 1024

WRAP_UP_MESSAGE = (
    "BUDGET ALMOST SPENT: this is the last step this run can afford. Finish now with the best "
    "answer you have."
)


class PreCallWorstCaseDetector(Detector):
    """Project the call's worst case against the remaining budget, before dispatch."""

    name = "pre_call_worst_case"

    def __init__(
        self,
        budget: Budget,
        price: PriceFn,
        default_max_output: int = DEFAULT_MAX_OUTPUT,
        caps_by_kind: Mapping[str, int] | None = None,
        wrap_up: bool = False,
        wrap_up_reserve: int = 1,
    ) -> None:
        self.wrap_up_reserve = max(1, wrap_up_reserve)
        self.budget = budget
        self._price = price
        self.default_max_output = default_max_output
        self.caps_by_kind = dict(caps_by_kind or {})
        self.wrap_up = wrap_up
        self._wrapped: set[str] = set()

    def reset(self, trace_id: str) -> None:
        self._wrapped.discard(trace_id)

    def _default_cap(self, request: CallRequest) -> int:
        kind = request.tags.get("call_kind")
        return (
            self.caps_by_kind.get(kind, self.default_max_output)
            if kind
            else self.default_max_output
        )

    def pre_call(self, request: CallRequest, view: LedgerView) -> Signal | None:
        sk = segment_key(request.attr, self.budget)
        if sk is None:
            return None
        left = view.budget_left(self.budget.budget_id, sk, self.budget.period)

        default_cap = self._default_cap(request)
        capped_out = (
            request.max_output_tokens if request.max_output_tokens is not None else default_cap
        )
        try:
            projected = self._price(
                request.provider, request.model, Usage(input=request.estimated_input_tokens)
            ) + self._price(request.provider, request.model, Usage(output=capped_out))
        except Exception as exc:  # unknown price → fail closed (HALT), never assume 0
            return Signal(
                detector=self.name,
                severity=Severity.TRIP,
                trace_id=request.attr.trace_id,
                reason=f"unknown price for {request.provider}/{request.model}; failing closed ({exc})",
                evidence={"fail_closed": True},
            )

        if projected >= left:
            return Signal(
                detector=self.name,
                severity=Severity.TRIP,
                trace_id=request.attr.trace_id,
                reason=f"worst-case {projected} >= remaining budget {left} (micros)",
                evidence={"projected": projected, "left": left, "capped_out": capped_out},
            )
        last_call = self.wrap_up and (self.wrap_up_reserve + 1) * projected >= left
        if last_call and request.attr.trace_id not in self._wrapped:
            self._wrapped.add(request.attr.trace_id)
            return Signal(
                detector=self.name,
                severity=Severity.WARN,
                trace_id=request.attr.trace_id,
                reason=f"budget almost spent: worst case {projected} fits {left} "
                f"at most {self.wrap_up_reserve}x (micros); "
                "asking for the final answer",
                evidence={
                    "set_cap": capped_out,
                    "projected": projected,
                    "left": left,
                    "wrap_up": True,
                },
            )
        if request.max_output_tokens is None:
            return Signal(
                detector=self.name,
                severity=Severity.WARN,
                trace_id=request.attr.trace_id,
                reason=f"output cap unset; bounding to {default_cap} so priced cap == enforced cap",
                evidence={"set_cap": default_cap, "projected": projected, "left": left},
            )
        return None


class PreCallWorstCasePolicy(Policy):
    name = "pre_call_worst_case"

    def decide(self, signal: Signal, view: LedgerView) -> Action:
        if signal.severity is Severity.TRIP:
            return Action(kind=ActionKind.HALT, trace_id=signal.trace_id, reason=signal.reason)
        # WARN → bound the output so the worst case we priced is the one enforced.
        raw_cap = signal.evidence.get("set_cap", DEFAULT_MAX_OUTPUT)
        cap = int(raw_cap) if isinstance(raw_cap, (int, float, str)) else DEFAULT_MAX_OUTPUT
        return Action(
            kind=ActionKind.MUTATE,
            trace_id=signal.trace_id,
            reason=signal.reason,
            max_output_tokens=cap,
            inject_message=WRAP_UP_MESSAGE if signal.evidence.get("wrap_up") else None,
        )


def build(
    budget: Budget,
    price: PriceFn,
    default_max_output: int = DEFAULT_MAX_OUTPUT,
    caps_by_kind: Mapping[str, int] | None = None,
    wrap_up: bool = False,
    wrap_up_reserve: int = 1,
) -> tuple[Detector, Policy]:
    detector = PreCallWorstCaseDetector(
        budget, price, default_max_output, caps_by_kind, wrap_up, wrap_up_reserve
    )
    return detector, PreCallWorstCasePolicy()
