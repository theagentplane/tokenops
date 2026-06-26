"""Phase 5b — ApplyControls + wrap_complete actually APPLY corrective controls."""

from __future__ import annotations

import pytest

from tokenops.control import (
    Action,
    ActionKind,
    ApplyControls,
    Budget,
    CallRequest,
    Governor,
    Halt,
    Ledger,
    Throttled,
    build_governor,
    wrap_complete,
)
from tokenops.control.policies import cost_budget, pre_call_worst_case
from conftest import make_attr, toy_price


# ---- ApplyControls unit -------------------------------------------------- #

def test_apply_mutate_sets_overrides():
    c = ApplyControls()
    c.begin_call()
    c.apply(Action(kind=ActionKind.MUTATE, run_id="r", max_output_tokens=1024, downgrade_to="cheap"))
    assert c.call.max_output_tokens == 1024 and c.call.model_override == "cheap"


def test_apply_inject_carries_message():
    c = ApplyControls()
    c.apply(Action(kind=ActionKind.INJECT, run_id="r", inject_message="be minimal"))
    assert c.carry == ["be minimal"]


def test_apply_reject_raises_throttled():
    c = ApplyControls()
    with pytest.raises(Throttled):
        c.apply(Action(kind=ActionKind.REJECT, run_id="r", retry_after_s=1.0))


def test_apply_halt_raises():
    c = ApplyControls()
    with pytest.raises(Halt):
        c.apply(Action(kind=ActionKind.HALT, run_id="r"))


# ---- wrap_complete e2e --------------------------------------------------- #

def _record_dispatch():
    calls = []

    def dispatch(provider, model, messages, max_output_tokens=None):
        calls.append({"model": model, "messages": messages, "max_output_tokens": max_output_tokens})
        from tokenops.providers.types import ModelResponse
        return ModelResponse(content="ok", input_tokens=10, output_tokens=5)

    return dispatch, calls


def test_worst_case_caps_the_dispatched_call():
    cap = Budget(budget_id="run_llm_cap", limit_micros=10_000_000, dimension="run")
    controls = ApplyControls()
    ledger = Ledger(budgets=[cap], price=toy_price)
    gov = Governor(ledger, controls)
    gov.register(*pre_call_worst_case.build(cap, toy_price, default_max_output=1024))
    attr = make_attr()
    ledger.open_run("run-1")

    dispatch, calls = _record_dispatch()
    governed = wrap_complete(gov, controls, attr, provider="openai", model="gpt-4o-mini", dispatch=dispatch)

    governed("openai", "gpt-4o-mini", [{"role": "user", "content": "hi"}])
    # the call left uncapped → MUTATE set the enforced output cap on the dispatched request
    assert calls[0]["max_output_tokens"] == 1024


def test_inject_message_prepended_to_next_dispatch():
    controls = ApplyControls()
    ledger = Ledger(budgets=[], price=toy_price)
    gov = Governor(ledger, controls)
    attr = make_attr()
    ledger.open_run("run-1")
    controls.carry.append("BUDGET PRESSURE: keep minimal")  # as an observe-side INJECT would

    dispatch, calls = _record_dispatch()
    governed = wrap_complete(gov, controls, attr, provider="openai", model="gpt-4o-mini", dispatch=dispatch)
    governed("openai", "gpt-4o-mini", [{"role": "user", "content": "hi"}])

    assert calls[0]["messages"][0] == {"role": "system", "content": "BUDGET PRESSURE: keep minimal"}
    assert controls.carry == []  # consumed


def test_pre_call_halt_blocks_dispatch():
    cap = Budget(budget_id="run_llm_cap", limit_micros=1_000, dimension="run")
    controls = ApplyControls()
    ledger = Ledger(budgets=[cap], price=toy_price)
    gov = Governor(ledger, controls)
    gov.register(*pre_call_worst_case.build(cap, toy_price))
    attr = make_attr()
    ledger.open_run("run-1")

    dispatch, calls = _record_dispatch()
    governed = wrap_complete(gov, controls, attr, provider="openai", model="gpt-4o-mini", dispatch=dispatch)
    with pytest.raises(Halt):
        governed("openai", "gpt-4o-mini", [{"role": "user", "content": "x" * 5000}])
    assert calls == []  # never dispatched
