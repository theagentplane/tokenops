"""cost_guard — edge-triggered minimization (INJECT) or downgrade (MUTATE)."""

from __future__ import annotations

from tokenops.control import ActionKind, Budget
from tokenops.control.policies import cost_guard
from conftest import make_attr, make_step, FakeView


CAP = Budget(budget_id="run_llm_cap", limit_micros=100_000, dimension="run")


def test_edge_trigger_fires_once():
    det, _ = cost_guard.build(CAP, threshold=0.8)
    v = FakeView(_budget_left=20_000)  # spent 80_000 → ratio 0.8
    assert det.observe(make_attr(), make_step(), v).severity.value == "warn"
    assert det.observe(make_attr(), make_step(), v) is None  # only once


def test_below_threshold_silent():
    det, _ = cost_guard.build(CAP, threshold=0.8)
    assert det.observe(make_attr(), make_step(), FakeView(_budget_left=30_000)) is None


def test_minimize_injects():
    det, pol = cost_guard.build(CAP, mode="minimize")
    sig = det.observe(make_attr(), make_step(), FakeView(_budget_left=10_000))
    a = pol.decide(sig, FakeView())
    assert a.kind is ActionKind.INJECT and "minimal" in a.inject_message.lower()


def test_downgrade_mutates():
    det, pol = cost_guard.build(CAP, mode="downgrade", downgrade_to="gpt-4o-mini")
    sig = det.observe(make_attr(), make_step(), FakeView(_budget_left=10_000))
    a = pol.decide(sig, FakeView())
    assert a.kind is ActionKind.MUTATE and a.downgrade_to == "gpt-4o-mini"
