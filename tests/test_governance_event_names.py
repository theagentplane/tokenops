"""Governance traces carry policy IDs, not guesses based on human-readable reasons."""

from __future__ import annotations

from dataclasses import replace

import pytest

from conftest import make_attr, toy_price
from tokenops.control import (
    Action,
    ActionKind,
    CallRequest,
    Governor,
    Halt,
    Ledger,
    Observation,
    PreviewControls,
    RaiseControls,
    Throttled,
    Usage,
    build_governance_stack,
    governance_events_payload,
    halt_detector_from_events,
)
from tokenops.control.context import (
    current_controls,
    reset_current_controls,
    set_current_controls,
)
from tokenops.control.core import Detector, Policy, Severity, Signal
from tokenops.control.models import GovernanceMode


@pytest.mark.parametrize("mode", [GovernanceMode.ENFORCE, GovernanceMode.PREVIEW])
@pytest.mark.parametrize(
    ("policy_id", "params", "moment", "kind"),
    [
        ("cost_budget", {"budget": "cap"}, "llm", ActionKind.HALT),
        ("pre_call_worst_case", {"budget": "cap"}, "pre_call", ActionKind.HALT),
        ("step_cap", {"max_steps": 1}, "tool", ActionKind.HALT),
        ("time_budget", {"max_seconds": 1.0}, "tool", ActionKind.HALT),
        ("concurrency_cap", {"max_concurrent": 1}, "pre_call", ActionKind.REJECT),
        ("tool_fix", {"registry": ["search"]}, "tool", ActionKind.INJECT),
        ("tool_output_cap", {"cap_tokens": 1}, "tool", ActionKind.INJECT),
        ("progress_guard", {"repeats": 1}, "tool", ActionKind.INJECT),
        ("cost_guard", {"budget": "cap"}, "llm", ActionKind.INJECT),
        ("context_compaction", {"ctx_max": 10}, "pre_call", ActionKind.MUTATE),
        ("output_runaway", {}, "llm", ActionKind.RETRY),
    ],
)
def test_governor_events_use_policy_id(policy_id, params, moment, kind, mode):
    governor, controls = build_governance_stack(
        {
            "budgets": [{"id": "cap", "limit_micros": 100}],
            "policies": {policy_id: params},
        },
        toy_price,
        mode=mode,
    )
    attr = make_attr()
    governor.ledger.open_run(attr.run_id)
    if policy_id == "concurrency_cap":
        governor.ledger.admit(f"run:{attr.run_id}")
    if policy_id == "context_compaction":
        controls.compaction_supported = True
    if policy_id == "time_budget":
        governor.observe(Observation(attr=attr, node_type="tool", boundary_id="search", ts=0.0))
        assert governance_events_payload(controls) == []
    previous_controls = current_controls()

    def trigger():
        if moment == "pre_call":
            governor.pre_call(
                CallRequest(
                    attr=attr,
                    provider="openai",
                    model="gpt-4o-mini",
                    estimated_input_tokens=10,
                )
            )
        else:
            governor.observe(
                Observation(
                    attr=attr,
                    node_type=moment,
                    boundary_id="search",
                    ts=1.0,
                    provider="openai",
                    model="gpt-4o-mini",
                    usage=Usage(input=10, output=1) if moment == "llm" else None,
                    input={"name": "serch", "args": {}},
                    output={"text": "loop " * 20},
                    signature="search-query",
                    result_hash="unchanged-result",
                )
            )

    if mode is GovernanceMode.ENFORCE and kind in (ActionKind.HALT, ActionKind.REJECT):
        with pytest.raises(Halt if kind is ActionKind.HALT else Throttled) as stopped:
            trigger()
        assert stopped.value.action.policy_id == policy_id
    else:
        trigger()

    assert current_controls() is previous_controls
    events = governance_events_payload(controls)
    assert len(events) == 1
    assert events[0]["policy"] == policy_id
    assert events[0]["kind"] == kind.value
    assert halt_detector_from_events(events) == (policy_id if kind is ActionKind.HALT else None)


@pytest.mark.parametrize("compaction_supported", [False, True])
def test_compaction_identity_and_capability_restore_outer_controls(compaction_supported):
    governor, controls = build_governance_stack(
        {"policies": {"context_compaction": {"ctx_max": 10}}},
        toy_price,
        mode=GovernanceMode.PREVIEW,
    )
    controls.compaction_supported = compaction_supported
    outer = PreviewControls(compaction_supported=not compaction_supported)
    token = set_current_controls(outer)
    try:
        governor.pre_call(
            CallRequest(
                attr=make_attr(),
                provider="openai",
                model="gpt-4o-mini",
                estimated_input_tokens=10,
            )
        )
        assert current_controls() is outer
        [action] = controls.actions
        assert action.policy_id == "context_compaction"
        expected = ActionKind.MUTATE if compaction_supported else ActionKind.ALLOW
        assert action.kind is expected
    finally:
        reset_current_controls(token)


def test_unknown_price_halt_has_exact_policy_id():
    governor, controls = build_governance_stack(
        {
            "budgets": [{"id": "cap", "limit_micros": 100}],
            "policies": {"pre_call_worst_case": {"budget": "cap"}},
        },
        toy_price,
        mode=GovernanceMode.PREVIEW,
    )
    governor.pre_call(CallRequest(attr=make_attr(), provider="unknown", model="unknown"))
    event = governance_events_payload(controls)[0]
    assert "unknown price" in event["reason"]
    assert event["policy"] == "pre_call_worst_case"


def test_explicit_policy_id_wins_over_misleading_reason():
    controls = PreviewControls()
    controls.apply(
        Action(
            kind=ActionKind.INJECT,
            run_id="r",
            policy_id="tool_output_cap",
            reason="output cap",
        )
    )
    assert governance_events_payload(controls)[0]["policy"] == "tool_output_cap"


def test_actions_without_policy_id_keep_legacy_reason_fallback():
    controls = PreviewControls()
    controls.apply(Action(kind=ActionKind.HALT, run_id="r", reason="budget 'cap' exhausted"))
    assert governance_events_payload(controls)[0]["policy"] == "cost_budget"


def test_policy_attribution_preserves_existing_action_equality_and_hashing():
    original = Action(kind=ActionKind.HALT, run_id="r", reason="step cap reached")
    attributed = replace(original, policy_id="step_cap")
    assert original.policy_id is None
    assert attributed.policy_id == "step_cap"
    assert original == attributed
    assert hash(original) == hash(attributed)


def test_fail_closed_controls_preserve_policy_id():
    with pytest.raises(Halt) as stopped:
        RaiseControls().apply(
            Action(kind=ActionKind.INJECT, run_id="r", policy_id="progress_guard")
        )
    assert stopped.value.action.policy_id == "progress_guard"


def test_custom_policy_keeps_its_registered_name():
    class CustomDetector(Detector):
        name = "my_custom_policy"

        def pre_call(self, request, view):
            return Signal(
                detector=self.name,
                severity=Severity.WARN,
                run_id=request.attr.run_id,
            )

    class CustomPolicy(Policy):
        name = "my_custom_policy"

        def decide(self, signal, view):
            return Action(kind=ActionKind.INJECT, run_id=signal.run_id)

    controls = PreviewControls()
    governor = Governor(Ledger(price=toy_price), controls)
    governor.register(CustomDetector(), CustomPolicy())
    governor.pre_call(CallRequest(attr=make_attr(), provider="openai", model="gpt-4o-mini"))
    assert governance_events_payload(controls)[0]["policy"] == "my_custom_policy"
