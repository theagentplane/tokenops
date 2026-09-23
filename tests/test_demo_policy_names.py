"""Demo views preserve canonical policy attribution and separate scenario IDs."""

from __future__ import annotations

import pytest
from examples.agents.types import TokenUsage
from examples.ui.demo_chips import (
    CHIPS,
    _cost_guard_event,
    governance_banner,
    live_governance_banner,
    prepare_chip_governance,
)
from examples.ui.simulator import SimulationResult, TraceEvent, _make_trace_governor, _TraceLog

from conftest import make_attr, toy_price
from tokenops.control import Halt, Observation, governance_events_payload
from tokenops.control.models import GovernanceMode, PolicyInstance, RunRegistration
from tokenops.control.store import Store
from tokenops.ui.policy_labels import policy_label


@pytest.fixture
def store(tmp_path):
    store = Store(str(tmp_path / "demo-names.db"), auto_seed=False)
    try:
        yield store
    finally:
        store.close()


@pytest.mark.parametrize("mode", [GovernanceMode.ENFORCE, GovernanceMode.PREVIEW])
def test_simulator_projects_exact_policy_ids_in_signals_and_actions(store, mode):
    store.upsert_policy_instance(
        PolicyInstance(id="research-limits", template="step_cap", params={"max_steps": 1})
    )
    log = _TraceLog()
    governor = _make_trace_governor(store, "research", log, toy_price, mode=mode)
    governor.ledger.open_run("run-1")
    observation = Observation(attr=make_attr(), node_type="tool", boundary_id="search", ts=1.0)
    if mode is GovernanceMode.ENFORCE:
        with pytest.raises(Halt):
            governor.observe(observation)
    else:
        governor.observe(observation)
    events = [event for event in log.events if event.category in ("signal", "action")]
    assert [event.category for event in events] == ["signal", "action"]
    assert all(event.detail["policy"] == "step_cap" for event in events)
    assert all(event.to_row()["policy"] == "step_cap" for event in events)
    assert governance_events_payload(governor.controls)[0]["policy"] == "step_cap"
    assert store.get_policy_instance("research-limits").template == "step_cap"


@pytest.mark.parametrize("policy_id", ["step_cap", "tool_fix", "custom_policy"])
def test_demo_reason_fallback_does_not_override_an_explicit_policy_id(policy_id):
    assert (
        _cost_guard_event(
            [{"policy": policy_id, "reason": "cost_guard budget pressure, minimizing"}]
        )
        is None
    )


@pytest.mark.parametrize("legacy_id", [None, "", "—"])
def test_demo_keeps_unidentified_legacy_event_fallback(legacy_id):
    event = {"policy": legacy_id, "reason": "budget pressure, minimizing"}
    assert _cost_guard_event([event]) is event


def test_demo_prefers_an_exact_identity_to_an_earlier_legacy_guess():
    legacy = {"reason": "minimizing"}
    canonical = {"policy": "cost_guard", "reason": "actual policy event"}
    assert _cost_guard_event([legacy, canonical]) is canonical


@pytest.mark.parametrize("policy_id", ["cost_budget", "pre_call_worst_case", "step_cap"])
def test_live_demo_halt_banner_names_the_actual_policy(policy_id):
    banner = live_governance_banner(
        "cost_cap",
        {
            "status": "halted",
            "halt_reason": "a limit was reached",
            "governance_events": [{"kind": "halt", "policy": policy_id}],
        },
        governance_mode=GovernanceMode.ENFORCE,
    )
    assert policy_label(policy_id) in banner


def test_live_demo_cost_guard_banner_uses_the_shared_label():
    banner = live_governance_banner(
        "cost_guard",
        {
            "status": "completed",
            "governance_events": [{"kind": "inject", "policy": "cost_guard"}],
        },
        governance_mode=GovernanceMode.ENFORCE,
    )
    assert policy_label("cost_guard") in banner


@pytest.mark.parametrize("policy_id", [None, "step_cap"])
def test_simulation_halt_banner_uses_identity_when_available(policy_id):
    result = SimulationResult(
        run_id="run-1",
        status="halted",
        summary="",
        findings=[],
        steps=[],
        token_usage=TokenUsage(),
        events=[
            TraceEvent(
                ts=1.0,
                category="action",
                title="halt",
                detail={"action": "halt", "policy": policy_id},
            )
        ],
        envelopes=[],
        research_window=[],
        summarize_window=[],
        research_cost_micros=0,
        summarize_cost_micros=0,
        halt_reason="a limit was reached",
        registration=RunRegistration(run_id="run-1"),
        trace_id="trace-1",
    )
    expected = policy_label(policy_id) if policy_id else "cost cap"
    assert f"**Governance · {expected}**" in governance_banner(result)


def test_legacy_live_halt_banner_keeps_its_existing_fallback():
    banner = live_governance_banner(
        "cost_cap",
        {"status": "halted", "halt_reason": "old event without identity"},
        governance_mode=GovernanceMode.ENFORCE,
    )
    assert "**Governance · budget cap**" in banner


def test_demo_scenario_and_seed_instance_ids_are_not_policy_aliases(store):
    assert {chip.id for chip in CHIPS} == {"cost_cap", "cost_guard"}
    prepare_chip_governance(store, "cost_cap")
    instance = store.get_policy_instance("seed_pre_call_worst_case")
    assert instance is not None
    assert instance.id == "seed_pre_call_worst_case"
    assert instance.template == "pre_call_worst_case"
    assert instance.params == {"default_max_output": 150}
    assert policy_label("pre_call_worst_case") in CHIPS[0].blurb
