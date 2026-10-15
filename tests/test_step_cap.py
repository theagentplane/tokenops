"""step_cap — opt-in step ceiling. HALT at exactly max_steps."""

from __future__ import annotations

import pytest

from conftest import FakeView, make_attr, make_step, toy_price
from tokenops.framework.core import ActionKind, Halt, Observation
from tokenops.framework.engine import Governor
from tokenops.framework.ledger import Budget, Ledger
from tokenops.framework.policies import step_cap


def test_detector_trips_at_cap():
    det, _ = step_cap.build(max_steps=3)
    assert det.observe(make_attr(), make_step(step=3), FakeView()).severity.value == "trip"


def test_detector_allows_below_cap():
    det, _ = step_cap.build(max_steps=3)
    assert det.observe(make_attr(), make_step(step=2), FakeView()) is None


def test_policy_halts():
    det, pol = step_cap.build(max_steps=3)
    sig = det.observe(make_attr(), make_step(step=3), FakeView())
    assert pol.decide(sig, FakeView()).kind is ActionKind.HALT


def test_e2e_halts_on_third_step():
    # tool crossings carry no cost, so this isolates step counting from budget.
    ledger = Ledger(
        budgets=[Budget(budget_id="c", limit_micros=10**9, dimension="trace")], price=toy_price
    )
    gov = Governor(ledger)
    gov.register(*step_cap.build(max_steps=3))
    attr = make_attr()
    ledger.open_run("run-1")

    def tool(i):
        gov.observe(
            Observation(
                attr=attr,
                node_type="tool",
                boundary_id="search",
                ts=float(i),
                signature=f"s{i}",
                result_hash=f"r{i}",
            )
        )

    tool(1)
    tool(2)
    with pytest.raises(Halt):
        tool(3)
    assert ledger.step_count("run-1") == 3
