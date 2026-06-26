"""pre_call_worst_case — preventive ceiling. MUTATE to cap output, HALT if still breaches."""

from __future__ import annotations

import pytest

from tokenops.control import ActionKind, Budget, CallRequest, Governor, Halt, Ledger, Observation, Usage
from tokenops.control.policies import pre_call_worst_case as pcwc
from conftest import make_attr, toy_price, FakeView, CollectingControls


CAP = Budget(budget_id="run_llm_cap", limit_micros=1_000_000, dimension="run")


def _req(est_in=1000, max_out=None):
    return CallRequest(attr=make_attr(), provider="openai", model="gpt-4o-mini",
                       estimated_input_tokens=est_in, max_output_tokens=max_out)


# ---- unit ---------------------------------------------------------------- #

def test_warn_sets_cap_when_unset_and_fits():
    det, pol = pcwc.build(CAP, toy_price, default_max_output=1024)
    # projected = 1000*10 + 1024*30 = 40_720 < 1_000_000 left, cap unset → WARN
    sig = det.pre_call(_req(max_out=None), FakeView(_budget_left=1_000_000))
    assert sig.severity.value == "warn"
    action = pol.decide(sig, FakeView())
    assert action.kind is ActionKind.MUTATE and action.max_output_tokens == 1024


def test_allow_when_cap_set_and_fits():
    det, _ = pcwc.build(CAP, toy_price)
    assert det.pre_call(_req(max_out=500), FakeView(_budget_left=1_000_000)) is None


def test_trip_when_worst_case_breaches():
    det, pol = pcwc.build(CAP, toy_price, default_max_output=1024)
    # left only 20_000; projected 40_720 ≥ 20_000 → TRIP
    sig = det.pre_call(_req(max_out=None), FakeView(_budget_left=20_000))
    assert sig.severity.value == "trip"
    assert pol.decide(sig, FakeView()).kind is ActionKind.HALT


def test_fail_closed_on_unknown_price():
    det, _ = pcwc.build(CAP, toy_price)
    req = CallRequest(attr=make_attr(), provider="openai", model="mystery",
                      estimated_input_tokens=10, max_output_tokens=10)
    sig = det.pre_call(req, FakeView(_budget_left=10**9))
    assert sig.severity.value == "trip" and sig.evidence.get("fail_closed") is True


# ---- e2e: MUTATE recorded through the Governor; TRIP raises --------------- #

def test_e2e_mutate_cap_recorded():
    ledger = Ledger(budgets=[CAP], price=toy_price)
    controls = CollectingControls()
    gov = Governor(ledger, controls)
    gov.register(*pcwc.build(CAP, toy_price, default_max_output=1024))
    ledger.open_run("run-1")
    gov.pre_call(_req(max_out=None))  # fits but cap unset → MUTATE
    muts = controls.of_kind(ActionKind.MUTATE)
    assert len(muts) == 1 and muts[0].max_output_tokens == 1024


def test_e2e_halts_when_spent_leaves_no_room():
    ledger = Ledger(budgets=[CAP], price=toy_price)
    gov = Governor(ledger)
    gov.register(*pcwc.build(CAP, toy_price))
    attr = make_attr()
    ledger.open_run("run-1")
    # burn almost the whole budget first
    ledger.record(Observation(attr=attr, node_type="llm", boundary_id="chat", ts=1.0,
                              provider="openai", model="gpt-4o-mini", usage=Usage(input=99_000, output=0)))
    with pytest.raises(Halt):
        gov.pre_call(_req(est_in=1000, max_out=None))
