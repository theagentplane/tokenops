"""cost_guard — edge-triggered minimization (INJECT) or downgrade (MUTATE)."""

from __future__ import annotations

from conftest import FakeView, make_attr, make_step
from tokenops.framework.core import ActionKind
from tokenops.framework.ledger import Budget
from tokenops.framework.policies import cost_guard

CAP = Budget(budget_id="run_llm_cap", limit_micros=100_000, dimension="trace")


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


def test_projected_trigger_fires_early_when_the_rate_will_not_fit():
    """Spent 30% only, but at 8,000/step the next 10 steps take it past the budget."""
    det, _ = cost_guard.build(CAP, horizon_steps=10)
    sig = det.observe(make_attr(), make_step(), FakeView(_budget_left=70_000, _velocity=8_000.0))
    assert sig is not None and sig.evidence["projected"] == 30_000 + 80_000
    assert "on course for 110%" in sig.reason


def test_projected_trigger_is_quiet_when_the_rate_fits():
    det, _ = cost_guard.build(CAP, horizon_steps=10)
    assert (
        det.observe(make_attr(), make_step(), FakeView(_budget_left=70_000, _velocity=5_000.0))
        is None
    )


def test_projected_trigger_is_off_by_default():
    det, _ = cost_guard.build(CAP)
    assert (
        det.observe(make_attr(), make_step(), FakeView(_budget_left=70_000, _velocity=1e9)) is None
    )
