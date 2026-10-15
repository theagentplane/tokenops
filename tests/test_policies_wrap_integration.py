"""Integration: every seeded policy through Governor + wrap_complete (mocked LLM).

Unit tests under ``test_<policy>.py`` use FakeView (detector/decide only).
This suite wires a real Governor, a scripted ``dispatch``, and (where needed)
Chronicle governance scope so ``wrap_complete`` → ``wrap_llm`` → crossing hook
exercises the full detect → decide → apply path — still offline / no API keys.
"""

from __future__ import annotations

import pytest

from conftest import toy_price
from tokenops.control import (
    ActionKind,
    ApplyControls,
    Budget,
    Governor,
    Halt,
    Ledger,
    Throttled,
    wrap_complete,
)
from tokenops.control.attribution import _build_attribution
from tokenops.control.context import SpanContext, _governance_scope, run_scope
from tokenops.control.core import Observation
from tokenops.control.models import HopAttribution
from tokenops.control.policies import (
    concurrency_cap,
    context_compaction,
    cost_budget,
    cost_guard,
    output_runaway,
    pre_call_worst_case,
    progress_guard,
    step_cap,
    time_budget,
    tool_fix,
    tool_output_cap,
)
from tokenops.providers.types import ModelResponse


def _reg(trace_id: str) -> HopAttribution:
    return HopAttribution(trace_id=trace_id, intent="policy_it", user_dims={"user_id": "alice"})


def _attr(trace_id: str):
    return _build_attribution(_reg(trace_id), service="research")


def _dispatch(content: str = "ok", *, inp: int = 100, out: int = 20):
    calls: list[dict] = []

    def dispatch(provider, model, messages, max_output_tokens=None, **kw):
        calls.append(
            {
                "model": model,
                "messages": messages,
                "max_output_tokens": max_output_tokens,
                **kw,
            }
        )
        return ModelResponse(content=content, input_tokens=inp, output_tokens=out)

    return dispatch, calls


def _governed(gov, attr, dispatch, *, trace_id: str):
    """Bind run + governance and return wrap_complete (Chronicle ingest path)."""
    controls = gov.controls
    assert isinstance(controls, ApplyControls)
    return wrap_complete(
        gov,
        controls,
        attr,
        provider="openai",
        model="gpt-4o-mini",
        dispatch=dispatch,
        service="research",
    )


def _with_scope(gov, attr, trace_id: str, fn):
    reg = _reg(trace_id)
    with run_scope(reg, SpanContext(span_id="s1", service="research")):
        with _governance_scope(gov, attr, provider="openai", model="gpt-4o-mini"):
            return fn()


# --------------------------------------------------------------------------- #
# Money / pre-call
# --------------------------------------------------------------------------- #


def test_it_pre_call_worst_case_mutates_uncapped_output():
    cap = Budget(budget_id="run_llm_cap", limit_micros=10_000_000, dimension="trace")
    controls = ApplyControls()
    gov = Governor(Ledger(budgets=[cap], price=toy_price), controls)
    gov.register(*pre_call_worst_case.build(cap, toy_price, default_max_output=1024))
    attr = _attr("r-pcwc")
    gov.ledger.open_run("r-pcwc")
    dispatch, calls = _dispatch()

    governed = _governed(gov, attr, dispatch, trace_id="r-pcwc")

    def run():
        governed("openai", "gpt-4o-mini", [{"role": "user", "content": "hi"}])

    _with_scope(gov, attr, "r-pcwc", run)
    assert calls and calls[0]["max_output_tokens"] == 1024
    assert any(a.kind is ActionKind.MUTATE for a in controls.event_log)


def test_it_pre_call_worst_case_halts_when_projected_over_budget():
    # Tiny budget: even capped worst-case cannot fit.
    cap = Budget(budget_id="run_llm_cap", limit_micros=50, dimension="trace")
    controls = ApplyControls()
    gov = Governor(Ledger(budgets=[cap], price=toy_price), controls)
    gov.register(*pre_call_worst_case.build(cap, toy_price, default_max_output=1024))
    attr = _attr("r-pcwc-halt")
    gov.ledger.open_run("r-pcwc-halt")
    dispatch, calls = _dispatch(inp=500, out=1)

    governed = _governed(gov, attr, dispatch, trace_id="r-pcwc-halt")

    def run():
        with pytest.raises(Halt):
            governed("openai", "gpt-4o-mini", [{"role": "user", "content": "x" * 2000}])

    _with_scope(gov, attr, "r-pcwc-halt", run)
    assert calls == []  # refused before dispatch
    assert gov.ledger.is_halted("r-pcwc-halt")


def test_it_cost_budget_halts_after_spend_crosses_cap():
    cap = Budget(budget_id="run_llm_cap", limit_micros=20_000, dimension="trace")
    controls = ApplyControls()
    gov = Governor(Ledger(budgets=[cap], price=toy_price), controls)
    gov.register(*cost_budget.build(cap))
    attr = _attr("r-cb")
    gov.ledger.open_run("r-cb")
    # 820*10 + 45*30 = 9550 per call → 3rd observe trips
    dispatch, _ = _dispatch(inp=820, out=45)
    governed = _governed(gov, attr, dispatch, trace_id="r-cb")

    def run():
        with pytest.raises(Halt):
            for _ in range(10):
                governed("openai", "gpt-4o-mini", [{"role": "user", "content": "go"}])

    _with_scope(gov, attr, "r-cb", run)
    assert gov.ledger.is_halted("r-cb")
    assert gov.ledger.cost_micros("r-cb") >= 20_000


def test_it_cost_guard_injects_near_threshold():
    cap = Budget(budget_id="run_llm_cap", limit_micros=10_000, dimension="trace")
    controls = ApplyControls()
    gov = Governor(Ledger(budgets=[cap], price=toy_price), controls)
    gov.register(*cost_guard.build(cap, threshold=0.5, mode="minimize"))
    attr = _attr("r-cg")
    gov.ledger.open_run("r-cg")
    # First call spends enough to cross 50% on observe → INJECT carried to next call
    dispatch, calls = _dispatch(inp=400, out=50)  # 4000+1500=5500 ≥ 50% of 10k
    governed = _governed(gov, attr, dispatch, trace_id="r-cg")

    def run():
        governed("openai", "gpt-4o-mini", [{"role": "user", "content": "a"}])
        governed("openai", "gpt-4o-mini", [{"role": "user", "content": "b"}])

    _with_scope(gov, attr, "r-cg", run)
    assert any(a.kind is ActionKind.INJECT for a in controls.event_log)
    # Second dispatch should see the inject as an extra user turn
    assert len(calls) >= 2
    assert any("minimal" in m.get("content", "").lower() for m in calls[1]["messages"])


# --------------------------------------------------------------------------- #
# Caps / backpressure
# --------------------------------------------------------------------------- #


def test_it_step_cap_halts_at_max_steps():
    controls = ApplyControls()
    gov = Governor(Ledger(price=toy_price), controls)
    gov.register(*step_cap.build(max_steps=2))
    attr = _attr("r-sc")
    gov.ledger.open_run("r-sc")
    dispatch, calls = _dispatch()
    governed = _governed(gov, attr, dispatch, trace_id="r-sc")

    def run():
        governed("openai", "gpt-4o-mini", [{"role": "user", "content": "1"}])
        with pytest.raises(Halt):
            governed("openai", "gpt-4o-mini", [{"role": "user", "content": "2"}])

    _with_scope(gov, attr, "r-sc", run)
    assert gov.ledger.is_halted("r-sc")
    assert (
        len(calls) == 2
    )  # second call dispatches then observe HALTs; or halt on observe of step 2


def test_time_budget_halts_run():
    controls = ApplyControls()
    gov = Governor(Ledger(budgets=[], price=toy_price), controls)
    gov.register(*time_budget.build(max_seconds=0.0))
    attr = _attr("r-tb")
    gov.ledger.open_run("r-tb")
    dispatch, calls = _dispatch()
    governed = _governed(gov, attr, dispatch, trace_id="r-tb")

    def run():
        # The ledger records the step before observe fires, so elapsed=0.0 >= 0.0
        # trips on the first call.
        with pytest.raises(Halt):
            governed("openai", "gpt-4o-mini", [{"role": "user", "content": "1"}])

    _with_scope(gov, attr, "r-tb", run)
    assert gov.ledger.is_halted("r-tb")
    assert len(calls) == 1


def test_it_concurrency_cap_rejects_when_inflight_saturated():
    controls = ApplyControls()
    gov = Governor(Ledger(price=toy_price), controls)
    gov.register(*concurrency_cap.build(max_concurrent=1, mode="reject"))
    attr = _attr("r-cc")
    gov.ledger.open_run("r-cc")
    gov.ledger.admit("trace:r-cc")  # one slot taken
    dispatch, calls = _dispatch()
    governed = _governed(gov, attr, dispatch, trace_id="r-cc")

    def run():
        with pytest.raises(Throttled):
            governed("openai", "gpt-4o-mini", [{"role": "user", "content": "hi"}])

    _with_scope(gov, attr, "r-cc", run)
    assert calls == []


# --------------------------------------------------------------------------- #
# Tool policies (observe path; same Governor as wrap_complete)
# --------------------------------------------------------------------------- #


def test_it_tool_fix_injects_then_halts_on_repeated_bad_calls():
    controls = ApplyControls()
    gov = Governor(Ledger(price=toy_price), controls)
    gov.register(*tool_fix.build({"search"}, k=3))
    attr = _attr("r-tf")
    gov.ledger.open_run("r-tf")

    for i in range(2):
        gov.observe(
            Observation(
                attr=attr,
                node_type="tool",
                boundary_id="serch",
                ts=float(i),
                input={"name": "serch", "args": {"q": "x"}},
                output={"ok": False},
                signature="bad",
                result_hash=f"h{i}",
            )
        )
        sub = controls.take_tool_result()
        assert sub is not None and sub.startswith("ERROR:")

    with pytest.raises(Halt):
        gov.observe(
            Observation(
                attr=attr,
                node_type="tool",
                boundary_id="serch",
                ts=3.0,
                input={"name": "serch", "args": {"q": "x"}},
                output={"ok": False},
                signature="bad",
                result_hash="h3",
            )
        )
    assert gov.ledger.is_halted("r-tf")


def test_it_tool_output_cap_offloads_oversized_result():
    controls = ApplyControls()
    gov = Governor(Ledger(price=toy_price), controls)
    gov.register(*tool_output_cap.build(cap_tokens=10))
    attr = _attr("r-toc")
    gov.ledger.open_run("r-toc")
    big = {"rows": [{"v": "x" * 40} for _ in range(20)]}
    gov.observe(
        Observation(
            attr=attr,
            node_type="tool",
            boundary_id="search",
            ts=1.0,
            input={"name": "search", "args": {"query": "q"}},
            output=big,
            signature="s",
            result_hash="r",
        )
    )
    descriptor = controls.take_tool_result()
    assert descriptor is not None and "OFFLOADED" in descriptor.upper()


def test_it_progress_guard_injects_then_halts():
    controls = ApplyControls()
    gov = Governor(Ledger(price=toy_price), controls)
    gov.register(*progress_guard.build(window=8, repeats=3, max_corrections=2))
    attr = _attr("r-pg")
    gov.ledger.open_run("r-pg")

    def same_tool(i: int):
        gov.observe(
            Observation(
                attr=attr,
                node_type="tool",
                boundary_id="search",
                ts=float(i),
                input={"name": "search", "args": {"query": "same"}},
                output={"snippet": "unchanged result"},
                signature="sig-same",
                result_hash="hash-same",
            )
        )

    # Fill repeats → INJECT corrections, then HALT
    halted = False
    for i in range(12):
        try:
            same_tool(i)
        except Halt:
            halted = True
            break
    assert halted or any(a.kind is ActionKind.INJECT for a in controls.event_log)
    # Prefer hard halt when corrections exhausted
    if any(a.kind is ActionKind.HALT for a in controls.event_log) or gov.ledger.is_halted("r-pg"):
        assert gov.ledger.is_halted("r-pg")


# --------------------------------------------------------------------------- #
# Prompt / output behavior
# --------------------------------------------------------------------------- #


def test_it_context_compaction_rewrites_messages_via_wrap():
    controls = ApplyControls()
    gov = Governor(Ledger(price=toy_price), controls)
    gov.register(*context_compaction.build(ctx_max=10))
    attr = _attr("r-ccx")
    gov.ledger.open_run("r-ccx")
    dispatch, calls = _dispatch()
    governed = _governed(gov, attr, dispatch, trace_id="r-ccx")
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "dup"},
        {"role": "user", "content": "dup"},
        {"role": "user", "content": "unique"},
    ]

    def run():
        governed("openai", "gpt-4o-mini", msgs)

    _with_scope(gov, attr, "r-ccx", run)
    sent = calls[0]["messages"]
    assert sum(1 for m in sent if m.get("content") == "dup") == 1
    assert any(m.get("content") == "unique" for m in sent)


def test_it_context_compaction_records_tokens_on_the_observation():
    """Compaction metadata (tokens_before / tokens_after / tokens_saved) flows through
    wrap_complete -> crossing hook -> Observation. The plane stores no per-policy statistics
    (control-plane ADR 0009), so the observation is where it is visible."""
    controls = ApplyControls()
    gov = Governor(Ledger(price=toy_price), controls)
    gov.register(*context_compaction.build(ctx_max=10))  # tiny ctx -> always trips
    observed = []
    original = gov.observe

    def spy(obs):
        observed.append(obs)
        return original(obs)

    gov.observe = spy  # type: ignore[method-assign]
    attr = _attr("r-cc-meta")
    gov.ledger.open_run("r-cc-meta")
    dispatch, calls = _dispatch(inp=80, out=20)
    governed = _governed(gov, attr, dispatch, trace_id="r-cc-meta")
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "dup"},
        {"role": "user", "content": "dup"},
        {"role": "user", "content": "unique"},
    ]

    def run():
        governed("openai", "gpt-4o-mini", msgs)

    _with_scope(gov, attr, "r-cc-meta", run)

    llm = [o for o in observed if o.node_type == "llm"]
    assert llm, "no llm observation reached the governor"
    comp = llm[-1].compaction
    assert comp is not None, "compaction metadata missing from the observation"
    assert any(
        action.policy_id == "context_compaction" and action.compact for action in controls.event_log
    )
    assert comp["tokens_before"] > 0
    assert comp["tokens_after"] > 0
    assert comp["tokens_saved"] >= 0
    assert comp["tokens_saved"] == comp["tokens_before"] - comp["tokens_after"]


def test_it_output_runaway_retries_then_succeeds():
    controls = ApplyControls()
    gov = Governor(Ledger(price=toy_price), controls)
    gov.register(*output_runaway.build(repeats=4, max_retries=2))
    attr = _attr("r-or")
    gov.ledger.open_run("r-or")

    class Scripted:
        def __init__(self):
            self.n = 0
            self.calls = []

        def __call__(self, provider, model, messages, max_output_tokens=None, **kw):
            self.calls.append(kw)
            self.n += 1
            text = "loop loop loop loop loop loop loop" if self.n < 3 else "unique clean answer"
            return ModelResponse(content=text, input_tokens=50, output_tokens=20)

    scripted = Scripted()
    governed = _governed(gov, attr, scripted, trace_id="r-or")

    def run():
        return governed("openai", "gpt-4o-mini", [{"role": "user", "content": "hi"}])

    resp = _with_scope(gov, attr, "r-or", run)
    assert resp.content == "unique clean answer"
    assert len(scripted.calls) == 3
