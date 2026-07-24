"""context_compaction — MUTATE the prompt near ctx_max; telemetry-only without a hook; never HALT."""

from __future__ import annotations

from conftest import FakeView, make_attr, make_step
from tokenops.control import ActionKind, CallRequest, Usage
from tokenops.control.policies import context_compaction


def _req(est):
    return CallRequest(
        attr=make_attr(), provider="openai", model="gpt-4o-mini", estimated_input_tokens=est
    )


def test_trips_at_ctx_max_and_mutates():
    det, pol = context_compaction.build(ctx_max=10_000)
    sig = det.pre_call(_req(10_000), FakeView())
    assert sig.severity.value == "warn"
    assert pol.decide(sig, FakeView()).kind is ActionKind.MUTATE


def test_below_silent():
    det, _ = context_compaction.build(ctx_max=10_000)
    assert det.pre_call(_req(5_000), FakeView()) is None


def test_rising_trend_trips_early():
    det, _ = context_compaction.build(ctx_max=10_000)
    steps = [make_step(node_type="llm", usage=Usage(input=x)) for x in (4000, 6000, 8000)]
    # est 6000 ≥ ctx_max//2 and input is rising across recent llm steps
    assert det.pre_call(_req(6000), FakeView(_recent=steps)) is not None


def test_no_hook_is_telemetry_only():
    det, pol = context_compaction.build(ctx_max=10_000, has_hook=False)
    sig = det.pre_call(_req(10_000), FakeView())
    assert pol.decide(sig, FakeView()).kind is ActionKind.ALLOW  # never HALT, never mutate
