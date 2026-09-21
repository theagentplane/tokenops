"""Exercise displayed policy labels without changing persisted template/instance IDs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from conftest import make_attr, toy_price
from tokenops.control import (
    Halt,
    Observation,
    build_governance_stack,
    build_governor,
    governance_events_payload,
    halt_detector_from_events,
)
from tokenops.control.config import POLICY_TEMPLATES, policy_template_ids
from tokenops.control.models import BudgetSpec, PolicyInstance, RunRecord
from tokenops.control.store import Store
from tokenops.ui.policy_labels import policy_label

VIEWS = Path(__file__).resolve().parents[1] / "src/tokenops/ui/views"


@pytest.fixture
def ui_store(tmp_path, monkeypatch):
    store = Store(str(tmp_path / "ui.db"), auto_seed=False)
    store.upsert_budget(BudgetSpec(id="cap", limit_micros=1_000_000))
    monkeypatch.setattr("tokenops.ui.store_client.get_store", lambda: store)
    try:
        yield store
    finally:
        store.close()


def _save_policy(app):
    return next(button for button in app.button if button.label == "Save policy").click().run()


@pytest.mark.parametrize("policy_id", policy_template_ids())
def test_admin_saves_canonical_template_with_a_user_owned_instance_id(ui_store, policy_id):
    app = AppTest.from_file(str(VIEWS / "admin.py"), default_timeout=10).run()
    assert not app.exception
    selector = app.selectbox(key="policy_template_(new)")
    assert selector.options == [policy_label(name) for name in policy_template_ids()]
    selector.select(policy_id).run()
    assert not app.exception
    assert app.selectbox(key="policy_template_(new)").value == policy_id
    template = POLICY_TEMPLATES[policy_id]
    assert json.loads(app.text_area(key=f"policy_params_(new)_{policy_id}").value) == dict(
        template.default_params
    )

    instance_id = f"configured-{policy_id}-instance"
    app.text_input(key="policy_id_(new)").set_value(instance_id)
    if template.requires_budget:
        next(selector for selector in app.selectbox if selector.label == "Budget").select("cap")
    _save_policy(app)
    assert not app.exception
    assert not app.error

    instance = ui_store.get_policy_instance(instance_id)
    assert instance is not None
    assert instance.id == instance_id
    assert instance.template == policy_id
    assert instance.params == dict(template.default_params)
    assert instance.budget_id == ("cap" if template.requires_budget else None)
    config = ui_store.governance_config_for("research")
    assert set(config["governance"]["policies"]) == {policy_id}
    assert set(build_governor(config, toy_price)._policy_by_name) == {policy_id}

    table = next(frame.value for frame in app.dataframe if "template" in frame.value.columns)
    assert table["id"].tolist() == [instance_id]
    assert table["template"].tolist() == [policy_id]
    assert table["policy"].tolist() == [policy_label(policy_id)]


def test_admin_template_change_does_not_rewrite_existing_instance_id(ui_store):
    ui_store.upsert_policy_instance(
        PolicyInstance(id="seed_tool_fix", template="tool_fix", params={"registry": ["lookup"]})
    )
    app = AppTest.from_file(str(VIEWS / "admin.py"), default_timeout=10).run()
    app.selectbox(key="edit_pol").select("seed_tool_fix").run()
    assert not app.exception
    assert app.text_input(key="policy_id_seed_tool_fix").value == "seed_tool_fix"
    assert json.loads(app.text_area(key="policy_params_seed_tool_fix_tool_fix").value) == {
        "registry": ["lookup"]
    }

    app.selectbox(key="policy_template_seed_tool_fix").select("step_cap").run()
    assert json.loads(app.text_area(key="policy_params_seed_tool_fix_step_cap").value) == {
        "max_steps": 20
    }
    _save_policy(app)
    assert not app.exception
    assert not app.error
    instance = ui_store.get_policy_instance("seed_tool_fix")
    assert instance is not None
    assert instance.id == "seed_tool_fix"
    assert instance.template == "step_cap"
    assert instance.params == {"max_steps": 20}
    assert ui_store.get_policy_instance("seed_step_cap") is None


def test_admin_can_disable_an_existing_unavailable_policy_without_renaming_it(ui_store):
    ui_store.upsert_policy_instance(
        PolicyInstance(id="old-trajectory", template="trajectory_hint", enabled=True)
    )
    app = AppTest.from_file(str(VIEWS / "admin.py"), default_timeout=10).run()
    assert not app.exception
    assert all(
        "trajectory_hint" not in option
        for option in app.selectbox(key="policy_template_(new)").options
    )
    app.selectbox(key="edit_pol").select("old-trajectory").run()
    assert not app.exception
    assert app.selectbox(key="policy_template_old-trajectory").value == "trajectory_hint"
    assert any("temporarily disabled" in warning.value for warning in app.warning)
    assert app.text_input(key="policy_id_old-trajectory").value == "old-trajectory"

    _save_policy(app)
    assert not app.exception
    assert any("temporarily disabled" in error.value for error in app.error)
    assert ui_store.get_policy_instance("old-trajectory").enabled is True

    next(checkbox for checkbox in app.checkbox if checkbox.label == "Enabled").uncheck()
    _save_policy(app)
    assert not app.exception
    assert not app.error
    instance = ui_store.get_policy_instance("old-trajectory")
    assert instance is not None
    assert instance.id == "old-trajectory"
    assert instance.template == "trajectory_hint"
    assert instance.enabled is False
    assert ui_store.governance_config_for("research")["governance"]["policies"] == {}


def test_dashboard_uses_the_same_labels_without_rewriting_trace_ids(ui_store):
    ui_store.upsert_policy_instance(
        PolicyInstance(id="research-limits", template="step_cap", params={"max_steps": 1})
    )
    ui_store.create_run(RunRecord(run_id="run-1", agent="research"))
    governor, controls = build_governance_stack(
        ui_store.governance_config_for("research"), toy_price, store=ui_store
    )
    governor.ledger.open_run("run-1")
    with pytest.raises(Halt) as stopped:
        governor.observe(
            Observation(attr=make_attr(), node_type="tool", boundary_id="search", ts=1.0)
        )
    events = governance_events_payload(controls)
    ui_store.update_run(
        "run-1",
        status="halted",
        halt_reason=stopped.value.action.reason,
        detector=halt_detector_from_events(events),
        governance_events=events,
    )
    app = AppTest.from_file(str(VIEWS / "dashboard.py"), default_timeout=10).run()
    assert not app.exception
    policy_table = next(frame.value for frame in app.dataframe if "template" in frame.value.columns)
    assert policy_table["template"].tolist() == ["step_cap"]
    assert policy_table["policy"].tolist() == [policy_label("step_cap")]
    trace = next(
        frame.value
        for frame in app.dataframe
        if "kind" in frame.value.columns and "policy" in frame.value.columns
    )
    assert trace["policy"].tolist() == [policy_label("step_cap")]
    assert any(policy_label("step_cap") in markdown.value for markdown in app.markdown)
    run = ui_store.get_run("run-1")
    assert run is not None
    assert run.detector == "step_cap"
    assert run.governance_events[0]["policy"] == "step_cap"
