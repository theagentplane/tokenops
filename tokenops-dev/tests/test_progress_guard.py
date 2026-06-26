"""progress_guard — inject correction on a stall; HALT after K corrections; needs unchanged result."""

from __future__ import annotations

from tokenops.control import ActionKind
from tokenops.control.policies import progress_guard
from conftest import make_attr, make_step, FakeView


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
