"""context_compaction — MUTATE the prompt near ctx_max; telemetry-only without a hook; never HALT."""

from __future__ import annotations

from conftest import FakeView, make_attr, make_step
from tokenops.control import ActionKind, CallRequest, Usage
from tokenops.control.context import reset_current_controls, set_current_controls
from tokenops.control.engine import ApplyControls
from tokenops.control.integration import _compact_messages
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


# --------------------------------------------------------------------------- #
# compaction token-recording tests (issue #143)                                #
# --------------------------------------------------------------------------- #

_MSGS = [
    {"role": "system", "content": "You are helpful."},
    {"role": "user", "content": "Hello"},
    {"role": "assistant", "content": "Hi there!"},
    {"role": "user", "content": "Hello"},  # duplicate — will be dropped
]


def _estimate(messages):
    return len(str(messages)) // 4


def test_compact_messages_returns_metadata_with_estimate():
    compacted, meta = _compact_messages(_MSGS, estimate=_estimate)
    assert len(compacted) < len(_MSGS)
    assert meta["tokens_before"] > 0
    assert meta["tokens_after"] > 0
    assert meta["tokens_saved"] == meta["tokens_before"] - meta["tokens_after"]
    assert meta["tokens_saved"] >= 0


def test_compact_messages_zeroed_metadata_without_estimate():
    compacted, meta = _compact_messages(_MSGS)
    assert len(compacted) < len(_MSGS)
    assert meta == {"tokens_before": 0, "tokens_after": 0, "tokens_saved": 0}


def test_compact_messages_drops_duplicates_preserves_system():
    compacted, _ = _compact_messages(_MSGS, estimate=_estimate)
    roles_and_content = [(m.get("role"), m.get("content")) for m in compacted]
    # System message always kept
    assert ("system", "You are helpful.") in roles_and_content
    # Duplicate user message dropped
    assert roles_and_content.count(("user", "Hello")) == 1


def test_observation_carry_compaction_when_present():
    from tokenops.control.core import Attribution, Observation

    obs = Observation(
        attr=Attribution(user="u", agent="a", trace_id="r"),
        node_type="llm",
        boundary_id="a.chat",
        ts=1.0,
        compaction={"tokens_before": 100, "tokens_after": 60, "tokens_saved": 40},
    )
    assert obs.compaction is not None
    assert obs.compaction["tokens_saved"] == 40


def test_observation_no_compaction_when_none():
    from tokenops.control.core import Attribution, Observation

    obs = Observation(
        attr=Attribution(user="u", agent="a", trace_id="r"),
        node_type="llm",
        boundary_id="a.chat",
        ts=1.0,
    )
    assert obs.compaction is None
