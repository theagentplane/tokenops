"""Store — CRUD, fail-closed validation, and governance_config_for round-trip."""

from __future__ import annotations

import pytest

from tokenops.control import build_governor
from tokenops.control.models import BudgetSpec, PolicyInstance, RunRecord, Segment
from tokenops.control.store import Store, new_id
from conftest import toy_price


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    yield s
    s.close()


def test_segment_budget_policy_crud(store):
    store.upsert_segment(Segment(id="seg_run", name="per run", dimension="run"))
    store.upsert_budget(BudgetSpec(id="run_llm_cap", limit_micros=20_000, dimension="run"))
    store.upsert_policy_instance(PolicyInstance(id="pi1", template="cost_budget",
                                                budget_id="run_llm_cap", agent="research"))
    assert store.get_segment("seg_run").dimension == "run"
    assert store.get_budget("run_llm_cap").limit_micros == 20_000
    assert store.get_policy_instance("pi1").template == "cost_budget"
    assert len(store.list_policy_instances()) == 1


def test_unknown_template_fails_closed(store):
    with pytest.raises(ValueError, match="unknown policy template"):
        store.upsert_policy_instance(PolicyInstance(id="x", template="nonsense"))


def test_governance_config_builds_a_governor(store):
    store.upsert_budget(BudgetSpec(id="run_llm_cap", limit_micros=20_000, dimension="run"))
    store.upsert_policy_instance(PolicyInstance(id="pi1", template="cost_budget",
                                                budget_id="run_llm_cap", agent="research"))
    store.upsert_policy_instance(PolicyInstance(id="pi2", template="step_cap",
                                                params={"max_steps": 5}))  # agent=None → all
    cfg = store.governance_config_for("research")
    # the assembled dict is exactly build_governor's input shape
    gov = build_governor(cfg, toy_price)
    assert set(gov._policy_by_name) == {"cost_budget", "step_cap"}
    assert gov.ledger.budget_left("run_llm_cap", "run:run-1") == 20_000


def test_agent_scoping(store):
    store.upsert_policy_instance(PolicyInstance(id="pi", template="step_cap",
                                                params={"max_steps": 3}, agent="summarize"))
    assert store.governance_config_for("research")["governance"]["policies"] == {}
    assert "step_cap" in store.governance_config_for("summarize")["governance"]["policies"]


def test_run_records_and_problematic_filter(store):
    store.create_run(RunRecord(run_id="r1", agent="research", status="completed", cost_micros=500))
    store.create_run(RunRecord(run_id="r2", agent="research", status="halted",
                               halt_reason="budget exhausted", detector="cost_budget", cost_micros=20_000))
    store.update_run("r1", ended_at=123.0)
    assert store.get_run("r1").ended_at == 123.0
    assert len(store.list_runs()) == 2
    problematic = store.list_runs(problematic_only=True)
    assert [r.run_id for r in problematic] == ["r2"]
    assert problematic[0].halt_reason == "budget exhausted"
