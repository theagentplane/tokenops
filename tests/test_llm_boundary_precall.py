"""LLM-kind @boundary runs pre_call via Chronicle on_enter (no wrap_complete)."""

from __future__ import annotations

import chronicle.session as chronicle_session
import pytest
from chronicle import boundary

from conftest import toy_price
from tokenops.control import ApplyControls, Halt, build_governor, install_crossing_hook
from tokenops.control.attribution import _build_attribution
from tokenops.control.context import clear, run_scope, _governance_scope
from tokenops.control.context import SpanContext
from tokenops.control.models import RunRegistration
from tokenops.control.store import Store
from tokenops.providers.types import ModelResponse


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "b.db"))
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _hooks():
    install_crossing_hook()


def test_llm_boundary_pre_call_halt(store):
    clear()
    reg = store.register_run(RunRegistration(run_id="r-halt"))
    config = {
        "governance": {
            "budgets": [{"id": "run_llm_cap", "limit_micros": 1, "dimension": "run"}],
            "policies": {
                "cost_budget": {"budget": "run_llm_cap"},
                "pre_call_worst_case": {"budget": "run_llm_cap", "default_max_output": 1024},
            },
        }
    }
    controls = ApplyControls()
    gov = build_governor(config, toy_price, controls)
    attr = _build_attribution(reg, service="agent")
    gov.ledger.open_run("r-halt")

    called = {"n": 0}

    @boundary("agent.chat", kind="llm")
    def chat(model: str, messages: list, *, max_output_tokens: int | None = None) -> ModelResponse:
        called["n"] += 1
        return ModelResponse(content="x", input_tokens=1, output_tokens=1)

    chronicle_session.reset_session().begin_trace("r-halt")
    with run_scope(reg, SpanContext(span_id="s1", service="agent")):
        with _governance_scope(gov, attr, provider="openai", model="gpt-4o-mini"):
            with pytest.raises(Halt):
                chat("gpt-4o-mini", [{"role": "user", "content": "hi"}])

    assert called["n"] == 0
    chronicle_session.reset_session()


def test_llm_boundary_mutate_max_output(store):
    clear()
    reg = store.register_run(RunRegistration(run_id="r-mut"))
    config = {
        "governance": {
            "budgets": [{"id": "run_llm_cap", "limit_micros": 10_000_000, "dimension": "run"}],
            "policies": {
                "pre_call_worst_case": {"budget": "run_llm_cap", "default_max_output": 256},
            },
        }
    }
    controls = ApplyControls()
    gov = build_governor(config, toy_price, controls)
    attr = _build_attribution(reg, service="agent")
    gov.ledger.open_run("r-mut")

    seen: dict = {}

    @boundary("agent.chat", kind="llm")
    def chat(model: str, messages: list, *, max_output_tokens: int | None = None) -> ModelResponse:
        seen["max_output_tokens"] = max_output_tokens
        return ModelResponse(content="ok", input_tokens=2, output_tokens=1)

    chronicle_session.reset_session().begin_trace("r-mut")
    with run_scope(reg, SpanContext(span_id="s1", service="agent")):
        with _governance_scope(gov, attr, provider="openai", model="gpt-4o-mini"):
            out = chat("gpt-4o-mini", [{"role": "user", "content": "hi"}])

    assert out.content == "ok"
    assert seen["max_output_tokens"] == 256
    chronicle_session.reset_session()
