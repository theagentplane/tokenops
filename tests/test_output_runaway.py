"""output_runaway — detect degenerate output; bounded RETRY then INJECT; never HALT."""

from __future__ import annotations

from conftest import FakeView, make_attr, make_step
from tokenops.framework.core import ActionKind
from tokenops.framework.policies import output_runaway


def _llm(text):
    return make_step(node_type="llm", output={"text": text})


def test_degenerate_output_detected():
    det, _ = output_runaway.build(repeats=4, domination=0.5)
    text = " ".join(["alpha beta gamma"] * 6)  # 3-gram repeats 6×
    assert det.observe(make_attr(), _llm(text), FakeView()).severity.value == "warn"


def test_clean_output_passes():
    det, _ = output_runaway.build()
    assert (
        det.observe(
            make_attr(), _llm("A concise unique summary of the pricing findings."), FakeView()
        )
        is None
    )


def test_bounded_retry_then_inject_never_halt():
    det, pol = output_runaway.build(repeats=4, max_retries=2)
    text = " ".join(["x y z"] * 8)
    attr = make_attr()
    kinds = []
    for _ in range(4):
        sig = det.observe(attr, _llm(text), FakeView())
        kinds.append(pol.decide(sig, FakeView()).kind)
    assert kinds[:3] == [ActionKind.RETRY, ActionKind.RETRY, ActionKind.INJECT]
    assert ActionKind.HALT not in kinds


def test_short_outputs_are_never_degenerate():
    """Below min_words the top word is always a big share: no signal, and a retry costs more."""
    det, _ = output_runaway.build()
    for text in (
        '{"action":[{"click":{"index":24}}]}',  # browser-use action JSON: one "word"
        '{"memory":"Found it.","action":[{"done":{"text":"OpenCV"}}]}',  # short final answer
        "ok",
    ):
        assert det.observe(make_attr(), _llm(text), FakeView()) is None, text


def test_min_words_is_configurable():
    loop = " ".join(["the"] * 8)
    assert output_runaway.build()[0].observe(make_attr(), _llm(loop), FakeView()) is None
    det, _ = output_runaway.build(min_words=4)
    assert det.observe(make_attr(), _llm(loop), FakeView()).severity.value == "warn"


def test_only_llm_with_text():
    det, _ = output_runaway.build()
    assert (
        det.observe(make_attr(), make_step(node_type="tool", output={"x": "y"}), FakeView()) is None
    )
