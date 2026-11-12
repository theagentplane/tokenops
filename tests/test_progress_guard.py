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


def _page(rh, step=1, **tags):
    return make_step(
        step,
        node_type="tool",
        boundary_id="web.page_state",
        signature="p",
        result_hash=rh,
        tags=tags,
    )


def test_corrections_reset_when_the_stalled_boundary_moves_on():
    """Two stalls far apart are two problems, not one run to halt (docs: 'with no progress')."""
    det, _ = progress_guard.build(window=6, repeats=3, max_corrections=1)
    attr, win = make_attr(), []

    def feed(rh):
        cur = _page(rh)
        win.append(cur)
        return det.observe(attr, cur, FakeView(_recent=win[-6:]))

    sigs = [feed("a") for _ in range(3)]  # stall 1 -> correction 1
    assert sigs[-1].evidence["correction"] == 1
    feed("b")  # the page changed: progress
    sigs = [feed("c") for _ in range(3)]  # stall 2 -> correction 1 again, not 2 (no halt)
    assert sigs[-1].evidence["correction"] == 1 and sigs[-1].severity.value == "warn"


def test_reset_on_progress_off_keeps_the_old_count():
    det, _ = progress_guard.build(window=6, repeats=3, max_corrections=1, reset_on_progress=False)
    attr, win = make_attr(), []
    for rh in ["a"] * 3 + ["b"] + ["c"] * 3:
        cur = _page(rh)
        win.append(cur)
        sig = det.observe(attr, cur, FakeView(_recent=win[-6:]))
    assert sig.evidence["correction"] == 2 and sig.severity.value == "trip"


def test_progress_signal_streak_injects_then_halts():
    det, pol = progress_guard.build(progress_streak=3, max_corrections=1)
    attr = make_attr()
    out = [det.observe(attr, _page(str(i), progress="no"), FakeView()) for i in range(6)]
    fired = [s for s in out if s]
    assert [i for i, s in enumerate(out) if s] == [2, 5]  # every 3rd "no"
    assert pol.decide(fired[0], FakeView()).kind is ActionKind.INJECT
    assert "finish now" in pol.decide(fired[0], FakeView()).inject_message
    assert pol.decide(fired[1], FakeView()).kind is ActionKind.HALT


def test_progress_yes_breaks_the_streak_and_resets():
    det, _ = progress_guard.build(progress_streak=3, max_corrections=1)
    attr = make_attr()
    seq = ["no", "no", "yes", "no", "no", "yes", "no", "no"]
    assert all(
        det.observe(attr, _page(str(i), progress=p), FakeView()) is None for i, p in enumerate(seq)
    )


def test_repeated_success_reports_are_not_a_stall():
    """Why a self-report is not fed through the repeated-result rule."""
    det, _ = progress_guard.build(window=6, repeats=3)
    attr, win = make_attr(), []
    for _ in range(5):
        cur = _page("same", progress="yes")
        win.append(cur)
        assert det.observe(attr, cur, FakeView(_recent=win[-6:])) is None


def test_blocked_page_injects_a_specific_message_then_halts():
    det, pol = progress_guard.build(max_corrections=2)
    attr = make_attr()
    sigs = [det.observe(attr, _page(str(i), blocked="yes"), FakeView()) for i in range(3)]
    acts = [pol.decide(s, FakeView()) for s in sigs]
    assert [a.kind for a in acts] == [ActionKind.INJECT, ActionKind.INJECT, ActionKind.HALT]
    assert "bot check" in acts[0].inject_message


def test_no_tags_is_the_old_behaviour():
    det, _ = progress_guard.build()
    assert det.observe(make_attr(), _page("x"), FakeView(_recent=[_page("x")])) is None


def test_wrap_up_asks_for_the_answer_once_before_halting():
    det, pol = progress_guard.build(progress_streak=1, max_corrections=1, wrap_up=True)
    attr = make_attr()
    acts = [
        pol.decide(det.observe(attr, _page(str(i), progress="no"), FakeView()), FakeView())
        for i in range(3)
    ]
    assert [a.kind for a in acts] == [ActionKind.INJECT, ActionKind.INJECT, ActionKind.HALT]
    assert (
        "Finish now" in acts[1].inject_message and "about to be stopped" in acts[1].inject_message
    )


def test_wrap_up_off_halts_as_before():
    det, pol = progress_guard.build(progress_streak=1, max_corrections=1)
    attr = make_attr()
    acts = [
        pol.decide(det.observe(attr, _page(str(i), progress="no"), FakeView()), FakeView())
        for i in range(2)
    ]
    assert [a.kind for a in acts] == [ActionKind.INJECT, ActionKind.HALT]


def test_grace_steps_hold_corrections_early_except_blocked_pages():
    det, _ = progress_guard.build(progress_streak=3, grace_steps=10)
    attr = make_attr()
    early = [
        det.observe(attr, _page(str(i), step=i + 1, progress="no"), FakeView()) for i in range(5)
    ]
    assert early == [None] * 5  # a streak of 5 inside the grace period: no correction yet
    late = det.observe(attr, _page("x", step=11, progress="no"), FakeView())
    assert late is not None and late.evidence["cause"] == "no_progress"  # the streak carried over
    det2, _ = progress_guard.build(grace_steps=10)
    assert det2.observe(attr, _page("b", step=1, blocked="yes"), FakeView()) is not None


def test_no_progress_message_leads_with_finishing():
    det, pol = progress_guard.build(progress_streak=1)
    sig = det.observe(make_attr(), _page("x", progress="no"), FakeView())
    msg = pol.decide(sig, FakeView()).inject_message
    assert "finish now" in msg and "Unless another approach is clearly" in msg


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
