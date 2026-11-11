"""progress_guard — inject correction on a stall; HALT after K corrections; needs unchanged result."""

from __future__ import annotations

from conftest import FakeView, make_attr, make_step
from tokenops.framework.core import ActionKind
from tokenops.framework.policies import progress_guard


def _tool(sig, rh):
    return make_step(node_type="tool", boundary_id="search", signature=sig, result_hash=rh)


def test_repeated_call_changed_result_is_progress():
    det, _ = progress_guard.build(window=6, repeats=3)
    window = [_tool("s", "r1"), _tool("s", "r2")]
    # same signature, DIFFERENT result_hash → progress, no trip
    cur = _tool("s", "r3")
    assert det.observe(make_attr(), cur, FakeView(_recent=window + [cur])) is None


def test_unchanged_result_injects_then_halts():
    det, pol = progress_guard.build(window=6, repeats=3, max_corrections=2)
    attr = make_attr()
    win = [_tool("s", "r")]
    # build up 3 identical (sig, result_hash) occurrences → stalled
    sigs = []
    for _ in range(4):
        cur = _tool("s", "r")
        win.append(cur)
        s = det.observe(attr, cur, FakeView(_recent=win[-6:]))
        if s:
            sigs.append(s)
    # first corrections WARN→INJECT, then escalates to TRIP→HALT
    kinds = [pol.decide(s, FakeView()).kind for s in sigs]
    assert ActionKind.INJECT in kinds and ActionKind.HALT in kinds


def test_llm_simhash_near_duplicate():
    det, _ = progress_guard.build(window=6, repeats=3, simhash_threshold=4)
    txt = "the pricing api returns the same thing again and again"
    steps = [make_step(node_type="llm", output={"text": txt}) for _ in range(3)]
    sig = det.observe(make_attr(), steps[-1], FakeView(_recent=steps))
    assert sig is not None and sig.severity.value == "warn"


def _call(content, n=1):
    return make_step(n, node_type="llm", input={"messages": [{"role": "user", "content": content}]})


def test_input_repeats_off_by_default():
    det, _ = progress_guard.build(window=6, repeats=3)
    steps = [_call("$ less", i) for i in range(5)]
    assert det.observe(make_attr(), steps[-1], FakeView(_recent=steps)) is None


def test_same_input_fires_when_replies_and_actions_vary():
    det, pol = progress_guard.build(window=6, repeats=3, input_repeats=3)
    steps = [_call("(END)\n  ", i) for i in range(3)]
    steps[1] = _call("(END) ", 1)  # whitespace-only difference still matches
    sig = det.observe(make_attr(), steps[-1], FakeView(_recent=steps))
    assert sig is not None
    assert pol.decide(sig, FakeView()).kind is ActionKind.INJECT


def test_changed_input_is_progress():
    det, _ = progress_guard.build(window=6, repeats=3, input_repeats=3)
    steps = [_call("a", 0), _call("b", 1), _call("a", 2)]
    assert det.observe(make_attr(), steps[-1], FakeView(_recent=steps)) is None


def test_input_parts_are_joined_and_missing_messages_ignored():
    det, _ = progress_guard.build(window=6, repeats=3, input_repeats=3)
    part = [{"type": "text", "text": "same"}, {"type": "image_url", "image_url": {}}]
    steps = [_call(part, i) for i in range(3)]
    assert det.observe(make_attr(), steps[-1], FakeView(_recent=steps)) is not None
    bare = [make_step(i, node_type="llm") for i in range(3)]
    assert det.observe(make_attr(), bare[-1], FakeView(_recent=bare)) is None


def test_input_simhash_threshold_matches_near_duplicates():
    base = "the terminal is still showing the pager with lines of git log output " * 3
    steps = [_call(f"{base} t={i}", i) for i in range(3)]
    exact, _ = progress_guard.build(window=6, repeats=3, input_repeats=3)
    assert exact.observe(make_attr(), steps[-1], FakeView(_recent=steps)) is None
    fuzzy, _ = progress_guard.build(window=6, repeats=3, input_repeats=3, input_simhash_threshold=8)
    assert fuzzy.observe(make_attr(), steps[-1], FakeView(_recent=steps)) is not None


def test_nudge_wording_matches_what_stalled():
    _, pol = progress_guard.build(window=6, repeats=3, input_repeats=3)
    det, _ = progress_guard.build(window=6, repeats=3, input_repeats=3)
    attr = make_attr()
    tools = [_tool("s", "r") for _ in range(3)]
    t = det.observe(attr, tools[-1], FakeView(_recent=tools))
    assert "same action with the same result" in pol.decide(t, FakeView()).inject_message
    txt = "the pricing api returns the same thing again and again"
    outs = [make_step(node_type="llm", output={"text": txt}) for _ in range(3)]
    o = det.observe(attr, outs[-1], FakeView(_recent=outs))
    assert "nearly identical" in pol.decide(o, FakeView()).inject_message
    ins = [_call("(END)", i) for i in range(3)]
    det.reset(attr.trace_id)  # a third correction in one run would be a HALT
    i = det.observe(attr, ins[-1], FakeView(_recent=ins))
    assert "same input" in pol.decide(i, FakeView()).inject_message
