"""Actuators on non-deterministic policies — RETRY, CANCEL, deep hooks.

Each drives the real governed wrappers with a *scripted* model so the non-deterministic
policies (output_runaway / progress_guard / context_compaction) fire deterministically.
"""

from __future__ import annotations

import chronicle.session as chronicle_session
from tokenops.control import ApplyControls, Governor, Ledger, build_attribution, wrap_complete
from tokenops.control.context import SpanContext, governance_scope, run_scope
from tokenops.control.models import RunRegistration
import pytest

from tokenops.control import Halt
from tokenops.control.core import Observation
from tokenops.control.integration import wrap_stream
from tokenops.control.policies import (
    context_compaction,
    output_runaway,
    progress_guard,
    tool_fix,
    tool_output_cap,
)
from tokenops.providers.types import ModelResponse
from conftest import toy_price


def _attr(run_id):
    return build_attribution(
        RunRegistration(run_id=run_id, intent="t", user_dims={"user_id": "alice"}),
        service="research",
    )

DEGENERATE = "loop loop loop loop loop loop loop loop"
CLEAN = "the quarterly pricing analysis is complete and unique"


class ScriptedModel:
    """Returns degenerate text for the first ``fail_n`` calls, then clean text."""

    def __init__(self, fail_n: int) -> None:
        self.fail_n = fail_n
        self.calls: list[dict] = []

    def __call__(self, provider, model, messages, max_output_tokens=None, **kw):
        i = len(self.calls)
        self.calls.append({"max_output_tokens": max_output_tokens, **kw})
        text = DEGENERATE if i < self.fail_n else CLEAN
        return ModelResponse(content=text, input_tokens=100, output_tokens=max(1, len(text) // 4))


def _bound_run(gov, attr, scripted):
    governed = wrap_complete(gov, gov.controls, attr, provider="openai", model="gpt-4o-mini",
                             dispatch=scripted, service="research")
    return governed


def test_retry_recovers_from_degenerate_output():
    ledger = Ledger(price=toy_price)
    controls = ApplyControls()
    gov = Governor(ledger, controls)
    gov.register(*output_runaway.build(repeats=4, max_retries=2))

    reg = RunRegistration(run_id="r1", intent="t", user_dims={"user_id": "alice"})
    attr = build_attribution(reg, service="research")
    ledger.open_run("r1")
    scripted = ScriptedModel(fail_n=2)
    governed = _bound_run(gov, attr, scripted)

    chronicle_session.reset_session().begin_trace("r1")
    with run_scope(reg, SpanContext(span_id="s", service="research")):
        with governance_scope(gov, attr, provider="openai", model="gpt-4o-mini"):
            resp = governed("openai", "gpt-4o-mini", [{"role": "user", "content": "hi"}])

    # 1 initial + 2 retries, ending on the clean output
    assert len(scripted.calls) == 3
    assert resp.content == CLEAN
    # retries raised penalties + tightened the cap; the first call did neither
    assert "frequency_penalty" not in scripted.calls[0]
    assert scripted.calls[1]["frequency_penalty"] == 1.0
    assert scripted.calls[2]["max_output_tokens"] < (scripted.calls[1]["max_output_tokens"] or 10**9)
    # every attempt was recorded to the ledger
    assert len([s for s in ledger.window("r1") if s.node_type == "llm"]) == 3


class ScriptedStream:
    """Degenerate token stream for the first ``fail_n`` calls, then a clean one. Records how
    many chunks each call actually emitted (to prove CANCEL cut the stream short)."""

    def __init__(self, fail_n: int) -> None:
        self.fail_n = fail_n
        self.calls: list[dict] = []
        self.emitted: list[int] = []

    def __call__(self, provider, model, messages, max_output_tokens=None, **kw):
        i = len(self.calls)
        self.calls.append({"max_output_tokens": max_output_tokens, **kw})
        self.emitted.append(0)
        degenerate = i < self.fail_n
        outer = self

        def gen():
            try:
                if degenerate:
                    for _ in range(200):       # would bleed 200 chunks if not cancelled
                        outer.emitted[i] += 1
                        yield "loop "
                else:
                    for w in CLEAN.split():
                        outer.emitted[i] += 1
                        yield w + " "
            except GeneratorExit:
                return

        return gen()


def test_cancel_tears_down_degenerate_stream_then_retries():
    ledger = Ledger(price=toy_price)
    controls = ApplyControls()
    gov = Governor(ledger, controls)
    gov.register(*output_runaway.build(repeats=4, max_retries=2))

    reg = RunRegistration(run_id="r2", intent="t", user_dims={"user_id": "alice"})
    attr = build_attribution(reg, service="research")
    ledger.open_run("r2")
    stream = ScriptedStream(fail_n=2)
    cancels = []
    governed = wrap_stream(gov, controls, attr, provider="openai", model="gpt-4o-mini",
                           stream_dispatch=stream, service="research",
                           ngram=3, repeats=4, check_every=4, on_cancel=lambda: cancels.append(1))

    chronicle_session.reset_session().begin_trace("r2")
    with run_scope(reg, SpanContext(span_id="s", service="research")):
        with governance_scope(gov, attr, provider="openai", model="gpt-4o-mini"):
            resp = governed("openai", "gpt-4o-mini", [{"role": "user", "content": "hi"}])

    # two degenerate streams were cancelled mid-flight, then a clean stream completed
    assert len(stream.calls) == 3
    assert sum(cancels) == 2
    assert resp.content.strip() == CLEAN
    # CANCEL cut the bleed: each degenerate stream emitted far fewer than its 200 chunks
    assert stream.emitted[0] < 20 and stream.emitted[1] < 20
    # the clean stream ran to completion
    assert stream.emitted[2] == len(CLEAN.split())


# ---- deep hooks ----------------------------------------------------------- #

def test_deep_compaction_rewrites_outgoing_messages():
    ledger = Ledger(price=toy_price)
    controls = ApplyControls()
    gov = Governor(ledger, controls)
    gov.register(*context_compaction.build(ctx_max=10, has_hook=True))  # tiny ctx → always trips
    attr = _attr("r3")
    ledger.open_run("r3")

    seen = {}

    def dispatch(p, m, messages, max_output_tokens=None, **kw):
        seen["messages"] = messages
        return ModelResponse(content=CLEAN, input_tokens=10, output_tokens=5)

    governed = wrap_complete(gov, controls, attr, provider="openai", model="gpt-4o-mini",
                             dispatch=dispatch, service="research")
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "dup"},
        {"role": "user", "content": "dup"},
        {"role": "user", "content": "unique"},
    ]
    governed("openai", "gpt-4o-mini", msgs)

    sent = seen["messages"]
    assert sum(1 for x in sent if x.get("content") == "dup") == 1   # duplicate dropped
    assert any(x.get("content") == "unique" for x in sent)          # unique kept


def test_deep_tool_result_substitution():
    ledger = Ledger(price=toy_price)
    controls = ApplyControls()
    gov = Governor(ledger, controls)
    gov.register(*tool_output_cap.build(cap_tokens=10))
    attr = _attr("r4")
    ledger.open_run("r4")

    big = {"rows": [{"k": i, "v": "x" * 20} for i in range(50)]}
    gov.observe(Observation(attr=attr, node_type="tool", boundary_id="search", ts=1.0,
                            input={"name": "search", "args": {"query": "q"}}, output=big,
                            signature="s", result_hash="r"))

    descriptor = controls.take_tool_result()
    assert descriptor is not None and descriptor.startswith("TOOL OUTPUT OFFLOADED")
    assert controls.take_tool_result() is None  # one-shot


def test_deep_tool_fix_substitutes_error_result():
    ledger = Ledger(price=toy_price)
    controls = ApplyControls()
    gov = Governor(ledger, controls)
    gov.register(*tool_fix.build({"search"}, k=3))
    attr = _attr("r6")
    ledger.open_run("r6")

    gov.observe(Observation(attr=attr, node_type="tool", boundary_id="serch", ts=1.0,
                            input={"name": "serch", "args": {"query": "q"}}, output={"x": "y"},
                            signature="s", result_hash="r"))

    sub = controls.take_tool_result()
    assert sub is not None and sub.startswith("ERROR:") and "did_you_mean=search" in sub


def test_progress_guard_injects_then_halts_on_repeated_results():
    ledger = Ledger(price=toy_price)
    controls = ApplyControls()
    gov = Governor(ledger, controls)
    gov.register(*progress_guard.build(window=8, repeats=3, max_corrections=2))
    attr = _attr("r5")
    ledger.open_run("r5")

    def feed():
        gov.observe(Observation(attr=attr, node_type="tool", boundary_id="search", ts=1.0,
                                input={"name": "search", "args": {"query": "q"}},
                                output={"snippet": "same", "completeness": 0.2},
                                signature="sig", result_hash="rh"))

    feed(); feed()           # count < repeats → no signal
    feed()                   # 3rd identical → correction 1 (INJECT)
    feed()                   # correction 2 (INJECT)
    with pytest.raises(Halt):
        feed()               # correction 3 > max_corrections → HALT
    assert ledger.is_halted("r5")
    assert controls.carry    # the injected corrections accumulated
