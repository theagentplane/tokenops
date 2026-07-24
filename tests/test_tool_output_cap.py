"""tool_output_cap — offload an oversized tool payload behind a handle (INJECT)."""

from __future__ import annotations

from conftest import FakeView, make_attr, make_step
from tokenops.control import ActionKind
from tokenops.control.policies import tool_output_cap
from tokenops.control.policies._util import est_tokens


def test_large_structured_payload_offloaded():
    det, pol = tool_output_cap.build(cap_tokens=100)
    big = {"rows": [{"k": i, "v": "x" * 20} for i in range(100)]}
    assert est_tokens(big) >= 100  # structured → /2.8
    sig = det.observe(
        make_attr(), make_step(node_type="tool", boundary_id="search", output=big), FakeView()
    )
    assert sig.severity.value == "warn"
    action = pol.decide(sig, FakeView())
    assert action.kind is ActionKind.INJECT and "handle=store://" in action.inject_message


def test_small_payload_passes():
    det, _ = tool_output_cap.build(cap_tokens=8000)
    assert (
        det.observe(
            make_attr(),
            make_step(
                node_type="tool",
                boundary_id="search",
                output={"snippet": "ok", "completeness": 0.9},
            ),
            FakeView(),
        )
        is None
    )


def test_divisor_is_content_aware():
    # same length text vs json: json uses the smaller divisor → more estimated tokens
    text = "word " * 100
    assert est_tokens(text) < est_tokens({"a": text})


def test_only_tool_nodes():
    det, _ = tool_output_cap.build(cap_tokens=1)
    assert (
        det.observe(make_attr(), make_step(node_type="llm", output={"text": "x" * 999}), FakeView())
        is None
    )
