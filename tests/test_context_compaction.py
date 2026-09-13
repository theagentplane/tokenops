"""context_compaction — MUTATE the prompt near ctx_max; telemetry-only without a hook; never HALT."""

from __future__ import annotations

from conftest import FakeView, make_attr, make_step
from tokenops.control import ActionKind, CallRequest, Usage
from tokenops.control.context import reset_current_controls, set_current_controls
from tokenops.control.engine import ApplyControls
from tokenops.control.policies import context_compaction


def _req(est):
    return CallRequest(
        attr=make_attr(), provider="openai", model="gpt-4o-mini", estimated_input_tokens=est
    )


def _with_compaction_supported():
    """Set up a controls context where compaction is supported (simulates wrap_complete)."""
    controls = ApplyControls()
    controls.compaction_supported = True
    tok = set_current_controls(controls)
    return tok


def test_trips_at_ctx_max_and_mutates():
    det, pol = context_compaction.build(ctx_max=10_000)
    sig = det.pre_call(_req(10_000), FakeView())
    assert sig.severity.value == "warn"
    tok = _with_compaction_supported()
    try:
        assert pol.decide(sig, FakeView()).kind is ActionKind.MUTATE
    finally:
        reset_current_controls(tok)


def test_below_silent():
    det, _ = context_compaction.build(ctx_max=10_000)
    assert det.pre_call(_req(5_000), FakeView()) is None


def test_rising_trend_trips_early():
    det, _ = context_compaction.build(ctx_max=10_000)
    steps = [make_step(node_type="llm", usage=Usage(input=x)) for x in (4000, 6000, 8000)]
    # est 6000 ≥ ctx_max//2 and input is rising across recent llm steps
    assert det.pre_call(_req(6000), FakeView(_recent=steps)) is not None


def test_no_hook_is_telemetry_only():
    """Without compaction_supported on controls, the policy returns ALLOW (telemetry only)."""
    det, pol = context_compaction.build(ctx_max=10_000)
    sig = det.pre_call(_req(10_000), FakeView())
    # No controls in context → compaction not supported → ALLOW
    assert pol.decide(sig, FakeView()).kind is ActionKind.ALLOW
