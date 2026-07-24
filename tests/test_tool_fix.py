"""tool_fix — inject correction for a bad tool call; HALT after K identical failures."""

from __future__ import annotations

from conftest import FakeView, make_attr, make_step
from tokenops.control import ActionKind
from tokenops.control.policies import tool_fix


def _tool_step(name, args=None):
    return make_step(node_type="tool", boundary_id=name, input={"name": name, "args": args or {}})


def test_valid_tool_passes():
    det, _ = tool_fix.build({"search"})
    assert det.observe(make_attr(), _tool_step("search", {"q": "x"}), FakeView()) is None


def test_unknown_tool_injects_with_suggestion():
    det, pol = tool_fix.build({"search"}, k=3)
    sig = det.observe(make_attr(), _tool_step("serch"), FakeView())
    assert sig.severity.value == "warn"
    assert sig.evidence["did_you_mean"] == "search"
    action = pol.decide(sig, FakeView())
    assert action.kind is ActionKind.INJECT and "search" in action.inject_message


def test_halts_after_k_identical_failures():
    det, pol = tool_fix.build({"search"}, k=3)
    attr = make_attr()
    sigs = [det.observe(attr, _tool_step("serch"), FakeView()) for _ in range(3)]
    assert [s.severity.value for s in sigs] == ["warn", "warn", "trip"]
    assert pol.decide(sigs[-1], FakeView()).kind is ActionKind.HALT


def test_missing_required_arg():
    det, _ = tool_fix.build({"search"}, schema={"search": {"required": ["q"]}})
    sig = det.observe(make_attr(), _tool_step("search", {}), FakeView())
    assert sig is not None and "missing_args" in sig.evidence["problem"]
