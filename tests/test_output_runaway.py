"""output_runaway — detect degenerate output; bounded RETRY then INJECT; never HALT."""

from __future__ import annotations

from tokenops.control import ActionKind
from tokenops.control.policies import output_runaway
from conftest import make_attr, make_step, FakeView


def _llm(text):
    return make_step(node_type="llm", output={"text": text})


def test_degenerate_output_detected():
    det, _ = output_runaway.build(repeats=4, domination=0.5)
    text = " ".join(["alpha beta gamma"] * 6)  # 3-gram repeats 6×
    assert det.observe(make_attr(), _llm(text), FakeView()).severity.value == "warn"


def test_clean_output_passes():
    det, _ = output_runaway.build()
    assert det.observe(make_attr(), _llm("A concise unique summary of the pricing findings."), FakeView()) is None


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


def test_only_llm_with_text():
    det, _ = output_runaway.build()
    assert det.observe(make_attr(), make_step(node_type="tool", output={"x": "y"}), FakeView()) is None
