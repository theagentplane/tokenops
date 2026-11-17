"""budget_pace — tell the model how much of a soft budget it has used, and how fast. Opt-in.

    Detect: after every model call, the run's cumulative spend as a percentage of
            ``soft_limit_micros``, kept for the last ``points`` calls.
    Fix:    INJECT one line on the next call: the current percentage and the earlier ones
            (t-1, t-2, ...), plus guidance that the limit is soft, so the model changes its
            strategy only where it expects no loss in quality.

It never halts and never trips: the hard stop stays with ``cost_budget``. The percentage may
pass 100; the line then says so. This is a pacing signal for the model to weigh, not a command.
"""

from __future__ import annotations

from collections import defaultdict, deque

from tokenops.framework.core import (
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

_GUIDANCE = (
    "This is a soft budget, not a hard limit. Change your strategy to spend less only if you "
    "expect no loss in the quality of your result; otherwise ignore it and do what gives the "
    "best result."
)


class BudgetPaceDetector(Detector):
    """WARN after each model call, carrying the recent spend percentages (newest first)."""

    name = "budget_pace"

    def __init__(self, soft_limit_micros: int, *, points: int = 3) -> None:
        if soft_limit_micros <= 0:
            raise ValueError("budget_pace: soft_limit_micros must be > 0")
        if points < 1:
            raise ValueError("budget_pace: points must be >= 1")
        self.soft_limit_micros = soft_limit_micros
        self.points = points
        self._pcts: dict[str, deque[int]] = defaultdict(lambda: deque(maxlen=self.points))

    def reset(self, trace_id: str) -> None:
        self._pcts.pop(trace_id, None)

    def observe(self, attr: Attribution, step: BoundaryStep, view: LedgerView) -> Signal | None:
        if step.node_type != "llm":
            return None
        history = self._pcts[attr.trace_id]
        history.append(round(100 * step.cum_spent_micros / self.soft_limit_micros))
        pcts = list(reversed(history))  # newest first: [now, t-1, t-2, ...]
        return Signal(
            detector=self.name,
            severity=Severity.WARN,
            trace_id=attr.trace_id,
            reason=f"budget pace: {pcts[0]}% of the soft budget used",
            evidence={"pcts": pcts, "soft_limit_micros": self.soft_limit_micros},
        )


def describe(pcts: list[int]) -> str:
    """``50% used (t-1: 41%, t-2: 35%)``, newest first."""
    earlier = ", ".join(f"t-{i}: {p}%" for i, p in enumerate(pcts[1:], start=1))
    return f"{pcts[0]}% used" + (f" ({earlier})" if earlier else "")


class BudgetPacePolicy(Policy):
    name = "budget_pace"

    def decide(self, signal: Signal, view: LedgerView) -> Action:
        pcts = [int(p) for p in signal.evidence["pcts"]]  # type: ignore[attr-defined]
        return Action(
            kind=ActionKind.INJECT,
            trace_id=signal.trace_id,
            reason=signal.reason,
            inject_message=f"BUDGET PACE: soft budget {describe(pcts)}. {_GUIDANCE}",
        )


def build(soft_limit_micros: int, *, points: int = 3) -> tuple[Detector, Policy]:
    return BudgetPaceDetector(soft_limit_micros, points=points), BudgetPacePolicy()
