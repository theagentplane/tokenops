"""Shared test helpers for the control plane.

Two tools that keep policy tests independent (one failure → one unit):

* ``FakeView`` — a ``LedgerView`` whose reads are fixed by constructor kwargs, so a
  detector can be tested with zero real ledger and zero other policies.
* ``CollectingControls`` — an OUT connector that records every Action (and still raises
  on HALT), so a corrective policy's MUTATE/INJECT can be asserted through the Governor
  before the real provider wrap exists.
"""

from __future__ import annotations

import os

# Tests expect an empty governance store unless they seed explicitly.
os.environ.setdefault("TOKENOPS_SKIP_GOVERNANCE_SEED", "1")

from dataclasses import dataclass, field

from tokenops.control.core import Action, ActionKind, Attribution, BoundaryStep, Halt, Usage


def toy_price(provider: str, model: str, usage: Usage) -> int:
    """micro-USD: 10/input token, 30/output token. Fail closed on unknown model."""
    if model not in {"gpt-4o-mini", "claude-sonnet-4-6"}:
        raise ValueError(f"unknown model {model!r}")
    return usage.input * 10 + usage.output * 30


def make_attr(run_id: str = "run-1", **kw) -> Attribution:
    base = dict(user="alice", agent="research", run_id=run_id)
    base.update(kw)
    return Attribution(**base)


def make_step(
    step: int = 1, *, node_type="llm", boundary_id="research.chat", cum=0, **kw
) -> BoundaryStep:
    return BoundaryStep(
        step=step,
        ts=float(step),
        node_type=node_type,
        boundary_id=boundary_id,
        cum_spent_micros=cum,
        **kw,
    )


@dataclass
class FakeView:
    """A LedgerView with reads pinned by constructor kwargs. Override only what a test needs."""

    _cost: int = 0
    _steps: int = 0
    _halted: bool = False
    _budget_left: int = 1_000_000
    _inflight: int = 0
    _velocity: float = 0.0
    _recent: list = field(default_factory=list)
    _window: list = field(default_factory=list)

    def cost_micros(self, run_id):
        return self._cost

    def step_count(self, run_id):
        return self._steps

    def is_halted(self, run_id):
        return self._halted

    def budget_left(self, budget_id, segment_key, period="lifetime"):
        return self._budget_left

    def inflight(self, segment_key):
        return self._inflight

    def velocity(self, run_id, m):
        return self._velocity

    def recent(self, run_id, n):
        return self._recent[-n:]

    def window(self, run_id):
        return self._window


@dataclass
class CollectingControls:
    """OUT connector that records actions. Still raises Halt on HALT (so kill-switch and
    sticky behaviour are exercised), but records corrective kinds for assertion."""

    actions: list = field(default_factory=list)

    def apply(self, action: Action) -> None:
        self.actions.append(action)
        if action.kind is ActionKind.HALT:
            raise Halt(action)

    def of_kind(self, kind: ActionKind):
        return [a for a in self.actions if a.kind is kind]
