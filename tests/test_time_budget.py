"""time_budget -- wall-clock ceiling per run. HALT when elapsed >= max_seconds."""

from __future__ import annotations

import pytest

from conftest import FakeView, make_attr, make_step, toy_price
from tokenops.control import ActionKind, Budget, Governor, Halt, Ledger, Observation
from tokenops.control.policies import time_budget


def test_detector_trips_at_ceiling():
    # First observe sets start=0.0; second observe with ts=61.0 → elapsed 61s >= 60s
    det, _ = time_budget.build(max_seconds=60.0)
    attr = make_attr()
    view = FakeView()
    det.observe(attr, make_step(step=0), view)  # sets start time
    sig = det.observe(attr, make_step(step=61), view)
    assert sig is not None
    assert sig.severity.value == "trip"


def test_detector_allows_below_ceiling():
    # First observe sets start=0.0; second observe with ts=59.0 → elapsed 59s < 60s
    det, _ = time_budget.build(max_seconds=60.0)
    attr = make_attr()
    view = FakeView()
    det.observe(attr, make_step(step=0), view)  # sets start time
    assert det.observe(attr, make_step(step=59), view) is None


def test_detector_first_step_allows():
    # First step for a run: elapsed is 0.0, always below any positive ceiling
    det, _ = time_budget.build(max_seconds=60.0)
    assert det.observe(make_attr(), make_step(step=1), FakeView()) is None


def test_policy_halts():
    det, pol = time_budget.build(max_seconds=60.0)
    attr = make_attr()
    view = FakeView()
    det.observe(attr, make_step(step=0), view)  # sets start time
    sig = det.observe(attr, make_step(step=61), view)
    assert pol.decide(sig, FakeView()).kind is ActionKind.HALT


def test_e2e_halts_when_time_exceeded():
    # The ledger records the step before observe fires, so window includes the current
    # step. With max_seconds=0.5: tool(0.0) → elapsed=0.0 < 0.5 (allow);
    # tool(1.0) → elapsed=1.0 - 0.0 = 1.0 >= 0.5 (HALT).
    ledger = Ledger(
        budgets=[Budget(budget_id="c", limit_micros=10**9, dimension="trace")], price=toy_price
    )
    gov = Governor(ledger)
    gov.register(*time_budget.build(max_seconds=0.5))
    attr = make_attr()
    ledger.open_run("run-1")

    def tool(ts):
        gov.observe(
            Observation(
                attr=attr,
                node_type="tool",
                boundary_id="search",
                ts=ts,
                signature=f"s{ts}",
                result_hash=f"r{ts}",
            )
        )

    tool(0.0)
    with pytest.raises(Halt):
        tool(1.0)
