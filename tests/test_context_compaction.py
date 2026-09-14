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


def test_compact_hoists_system_into_stable_prefix():
    from tokenops.control.integration import _compact_messages

    msgs = [
        {"role": "user", "content": "u1"},
        {"role": "system", "content": "sys-a"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u1"},  # duplicate of first user turn
        {"role": "system", "content": "sys-b"},
    ]
    out = _compact_messages(msgs)
    # system messages hoisted to the front, in their original relative order
    assert [m["role"] for m in out[:2]] == ["system", "system"]
    assert [m["content"] for m in out[:2]] == ["sys-a", "sys-b"]
    # tail keeps non-system order and drops the duplicate user turn
    assert [m["content"] for m in out[2:]] == ["u1", "a1"]


def test_compact_is_noop_when_system_already_first():
    from tokenops.control.integration import _compact_messages

    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
    ]
    assert _compact_messages(msgs) == msgs
