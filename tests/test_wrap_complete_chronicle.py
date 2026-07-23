"""§18 — wrap_complete observes LLM via Chronicle wrap_llm + crossing hook."""

from __future__ import annotations

from tokenops.control.attribution import _build_attribution

import chronicle.session as chronicle_session
from chronicle import get_session

from tokenops.control import (
    ApplyControls,
    Governor,
    Ledger,
    install_crossing_hook,
    wrap_complete,
)
from tokenops.control.context import SpanContext, _governance_scope, run_scope
from tokenops.control.models import RunRegistration
from tokenops.providers.types import ModelResponse
from conftest import toy_price


def _scripted(content: str = "hello", inp: int = 10, out: int = 5):
    calls: list[dict] = []

    def dispatch(provider, model, messages, max_output_tokens=None, **kw):
        calls.append({"provider": provider, "model": model, "messages": messages})
        return ModelResponse(content=content, input_tokens=inp, output_tokens=out)

    return dispatch, calls


def test_wrap_complete_observes_via_crossing_hook_once():
    """Governed dispatch records one Chronicle envelope and one ledger LLM step."""
    install_crossing_hook()
    ledger = Ledger(price=toy_price)
    controls = ApplyControls()
    gov = Governor(ledger, controls)
    reg = RunRegistration(run_id="r-w4", intent="t", user_dims={"user_id": "alice"})
    attr = _build_attribution(reg, service="research")
    ledger.open_run("r-w4")

    dispatch, calls = _scripted()
    governed = wrap_complete(
        gov, controls, attr,
        provider="openai", model="gpt-4o-mini",
        dispatch=dispatch, service="research",
    )

    chronicle_session.reset_session().begin_trace("r-w4")
    session = get_session()
    with run_scope(reg, SpanContext(span_id="s1", service="research")):
        with _governance_scope(gov, attr, provider="openai", model="gpt-4o-mini"):
            resp = governed("openai", "gpt-4o-mini", [{"role": "user", "content": "hi"}])

    assert resp.content == "hello"
    assert len(calls) == 1
    assert len(session.recorded_envelopes) == 1
    assert session.recorded_envelopes[0].boundary_kind == "llm"
    assert session.recorded_envelopes[0].node_id == "research.chat"
    llm_steps = [s for s in ledger.window("r-w4") if s.node_type == "llm"]
    assert len(llm_steps) == 1  # no double-billing
    assert llm_steps[0].boundary_id == "research.chat"


def test_wrap_complete_no_ledger_without_governance_scope():
    """Chronicle still traces; TokenOps ledger stays quiet without bound governance."""
    install_crossing_hook()
    ledger = Ledger(price=toy_price)
    controls = ApplyControls()
    gov = Governor(ledger, controls)
    reg = RunRegistration(run_id="r-bare", intent="t", user_dims={"user_id": "alice"})
    attr = _build_attribution(reg, service="research")
    ledger.open_run("r-bare")

    dispatch, _ = _scripted()
    governed = wrap_complete(
        gov, controls, attr,
        provider="openai", model="gpt-4o-mini",
        dispatch=dispatch, service="research",
    )

    chronicle_session.reset_session().begin_trace("r-bare")
    session = get_session()
    # No run_scope / governance binding — crossing hook no-ops for TokenOps ingest
    governed("openai", "gpt-4o-mini", [{"role": "user", "content": "hi"}])

    assert len(session.recorded_envelopes) == 1
    assert ledger.step_count("r-bare") == 0
