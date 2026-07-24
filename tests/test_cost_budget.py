"""cost_budget — the guarantee. Trips a sticky HALT when an accumulator is exhausted."""

from __future__ import annotations

import pytest

from conftest import FakeView, make_attr, make_step, toy_price
from tokenops.control import ActionKind, Budget, Governor, Halt, Ledger, Observation, Usage
from tokenops.control.policies import cost_budget

CAP = Budget(budget_id="run_llm_cap", limit_micros=20_000, dimension="run")


# ---- unit: detector + policy in isolation (FakeView) --------------------- #


def test_detector_trips_when_exhausted():
    det, _ = cost_budget.build(CAP)
    sig = det.observe(make_attr(), make_step(), FakeView(_budget_left=0))
    assert sig is not None and sig.severity.value == "trip"


def test_detector_allows_with_headroom():
    det, _ = cost_budget.build(CAP)
    assert det.observe(make_attr(), make_step(), FakeView(_budget_left=1)) is None


def test_policy_maps_trip_to_halt():
    det, pol = cost_budget.build(CAP)
    sig = det.observe(make_attr(), make_step(), FakeView(_budget_left=0))
    action = pol.decide(sig, FakeView())
    assert action.kind is ActionKind.HALT


# ---- e2e: through the Governor + real Ledger ----------------------------- #


def test_e2e_sticky_halt_and_kill_switch():
    ledger = Ledger(budgets=[CAP], price=toy_price)
    gov = Governor(ledger)
    gov.register(*cost_budget.build(CAP))
    attr = make_attr()
    ledger.open_run("run-1")

    def llm():
        gov.observe(
            Observation(
                attr=attr,
                node_type="llm",
                boundary_id="chat",
                ts=1.0,
                provider="openai",
                model="gpt-4o-mini",
                usage=Usage(input=820, output=45),
            )
        )

    llm()
    llm()  # 9550 * 2 = 19100 < 20000
    with pytest.raises(Halt):
        llm()  # 28650 ≥ 20000 → trip
    assert ledger.is_halted("run-1")
    # kill switch refuses the next call even if the agent swallowed the first Halt
    with pytest.raises(Halt) as exc:
        llm()
    assert "already halted" in exc.value.action.reason
