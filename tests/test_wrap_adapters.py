"""§12 — OpenAI-shaped dispatch and LangChain GovernedChatModel share wrap_complete."""

from __future__ import annotations

from tokenops.control.attribution import _build_attribution

import pytest
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


def _bound(gov, attr, dispatch, *, service: str = "research"):
    return wrap_complete(
        gov, gov.controls, attr,
        provider="openai", model="gpt-4o-mini",
        dispatch=dispatch, service=service,
    )


def test_openai_shaped_dispatch_with_wrap_complete_and_chronicle():
    install_crossing_hook()
    ledger = Ledger(price=toy_price)
    controls = ApplyControls()
    gov = Governor(ledger, controls)
    reg = RunRegistration(run_id="r-oai", intent="t", user_dims={"user_id": "alice"})
    attr = _build_attribution(reg, service="planner")
    ledger.open_run("r-oai")

    def dispatch(provider, model, messages, max_output_tokens=None, **kw):
        assert provider == "openai"
        assert model == "gpt-4o-mini"
        assert messages[0]["role"] == "user"
        return ModelResponse(content="plan: ok", input_tokens=20, output_tokens=8)

    governed = _bound(gov, attr, dispatch, service="planner")
    chronicle_session.reset_session().begin_trace("r-oai")
    session = get_session()

    with run_scope(reg, SpanContext(span_id="s", service="planner")):
        with _governance_scope(gov, attr, provider="openai", model="gpt-4o-mini"):
            out = governed("openai", "gpt-4o-mini", [{"role": "user", "content": "goal"}])

    assert out.content == "plan: ok"
    assert len(session.recorded_envelopes) == 1
    assert session.recorded_envelopes[0].boundary_kind == "llm"
    assert len([s for s in ledger.window("r-oai") if s.node_type == "llm"]) == 1


def test_langchain_governed_chat_model_with_wrap_complete():
    pytest.importorskip("langchain_core")
    # Optional stack can SIGFPE on import (transformers/numpy) — probe in a subprocess.
    import subprocess
    import sys

    probe = subprocess.run(
        [sys.executable, "-c", "from tokenops.adapters.langchain import GovernedChatModel"],
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        pytest.skip(f"langchain adapter unavailable: {probe.stderr.strip() or probe.returncode}")

    from langchain_core.messages import HumanMessage
    from tokenops.adapters.langchain import GovernedChatModel

    install_crossing_hook()
    ledger = Ledger(price=toy_price)
    controls = ApplyControls()
    gov = Governor(ledger, controls)
    reg = RunRegistration(run_id="r-lc", intent="t", user_dims={"user_id": "alice"})
    attr = _build_attribution(reg, service="writer")
    ledger.open_run("r-lc")

    def dispatch(provider, model, messages, max_output_tokens=None, **kw):
        # Messages arrived as OpenAI-shaped dicts from GovernedChatModel
        assert isinstance(messages[0], dict)
        return ModelResponse(content="lc answer", input_tokens=12, output_tokens=4)

    governed = _bound(gov, attr, dispatch, service="writer")
    llm = GovernedChatModel(governed, provider="openai", model="gpt-4o-mini")

    chronicle_session.reset_session().begin_trace("r-lc")
    session = get_session()

    with run_scope(reg, SpanContext(span_id="s", service="writer")):
        with _governance_scope(gov, attr, provider="openai", model="gpt-4o-mini"):
            result = llm.invoke([HumanMessage(content="write it")])

    assert result.content == "lc answer"
    assert len(session.recorded_envelopes) == 1
    assert session.recorded_envelopes[0].node_id == "writer.chat"
    llm_steps = [s for s in ledger.window("r-lc") if s.node_type == "llm"]
    assert len(llm_steps) == 1  # GovernedChatModel → wrap_complete → wrap_llm, once
