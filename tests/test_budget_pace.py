"""budget_pace — inject the soft-budget percentage and its recent trend; never halt."""

from __future__ import annotations

import pytest

from conftest import FakeView, make_attr, make_step
from tokenops.framework.config import build_governor
from tokenops.framework.core import ActionKind, Severity
from tokenops.framework.policies import budget_pace


def _llm(n, cum):
    return make_step(n, node_type="llm", cum=cum)


def _inject(det, pol, attr, step):
    sig = det.observe(attr, step, FakeView())
    assert sig is not None and sig.severity is Severity.WARN
    action = pol.decide(sig, FakeView())
    assert action.kind is ActionKind.INJECT
    return action.inject_message


def test_first_call_has_only_the_current_percentage():
    det, pol = budget_pace.build(1000)
    msg = _inject(det, pol, make_attr(), _llm(1, 350))
    assert "35% used" in msg and "t-1" not in msg


def test_trend_lists_current_then_two_earlier_calls():
    det, pol = budget_pace.build(1000)
    attr = make_attr()
    for n, cum in enumerate([350, 410], start=1):
        det.observe(attr, _llm(n, cum), FakeView())
    msg = _inject(det, pol, attr, _llm(3, 500))
    assert "50% used (t-1: 41%, t-2: 35%)" in msg


def test_only_the_last_three_points_are_kept():
    det, pol = budget_pace.build(1000)
    attr = make_attr()
    for n, cum in enumerate([100, 200, 300], start=1):
        det.observe(attr, _llm(n, cum), FakeView())
    msg = _inject(det, pol, attr, _llm(4, 400))
    assert "40% used (t-1: 30%, t-2: 20%)" in msg and "10%" not in msg


def test_guidance_says_soft_and_conditional_on_quality():
    det, pol = budget_pace.build(1000)
    msg = _inject(det, pol, make_attr(), _llm(1, 500))
    assert "soft budget, not a hard limit" in msg
    assert "no loss in the quality" in msg


def test_over_the_limit_is_reported_not_halted():
    det, pol = budget_pace.build(1000)
    msg = _inject(det, pol, make_attr(), _llm(1, 1250))
    assert "125% used" in msg


def test_tool_steps_are_ignored_and_do_not_count_as_a_point():
    det, pol = budget_pace.build(1000)
    attr = make_attr()
    det.observe(attr, _llm(1, 200), FakeView())
    assert det.observe(attr, make_step(2, node_type="tool", cum=200), FakeView()) is None
    assert "(t-1: 20%)" in _inject(det, pol, attr, _llm(3, 300))


def test_runs_are_tracked_separately_and_reset_clears():
    det, pol = budget_pace.build(1000)
    a, b = make_attr(trace_id="a"), make_attr(trace_id="b")
    det.observe(a, _llm(1, 900), FakeView())
    assert "t-1" not in _inject(det, pol, b, _llm(1, 100))
    det.reset("a")
    assert "t-1" not in _inject(det, pol, a, _llm(2, 950))


@pytest.mark.parametrize("kw", [{"soft_limit_micros": 0}, {"soft_limit_micros": 10, "points": 0}])
def test_invalid_parameters_fail_closed(kw):
    with pytest.raises(ValueError):
        budget_pace.build(kw.pop("soft_limit_micros"), **kw)


def test_config_key_builds_the_policy_and_requires_the_limit():
    gov = build_governor(
        {"policies": {"budget_pace": {"soft_limit_micros": 1000}}}, price=lambda *a, **k: 0
    )
    assert [d.name for d in gov._detectors] == ["budget_pace"]
    with pytest.raises(KeyError):
        build_governor({"policies": {"budget_pace": {}}}, price=lambda *a, **k: 0)
