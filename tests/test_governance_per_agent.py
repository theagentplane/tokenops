"""Per-agent governance config filtering for Governor builds."""

from __future__ import annotations

from tokenops.control.config import build_governor
from tokenops.control.models import BudgetSpec, PolicyInstance
from tokenops.control.store import Store
from conftest import toy_price


def test_governance_config_for_filters_by_agent(tmp_path):
    store = Store(str(tmp_path / "gov.db"), auto_seed=False)
    store.upsert_budget(BudgetSpec(id="cap", limit_micros=1_000_000, dimension="run"))
    store.upsert_policy_instance(
        PolicyInstance(
            id="global-budget",
            template="cost_budget",
            budget_id="cap",
            agent=None,
        )
    )
    store.upsert_policy_instance(
        PolicyInstance(
            id="researcher-steps",
            template="step_cap",
            params={"max_steps": 3},
            agent="researcher",
        )
    )
    store.upsert_policy_instance(
        PolicyInstance(
            id="planner-steps",
            template="step_cap",
            params={"max_steps": 50},
            agent="planner",
        )
    )

    researcher_cfg = store.governance_config_for("researcher")["governance"]["policies"]
    planner_cfg = store.governance_config_for("planner")["governance"]["policies"]

    assert researcher_cfg["cost_budget"]["budget"] == "cap"
    assert planner_cfg["cost_budget"]["budget"] == "cap"
    assert researcher_cfg["step_cap"]["max_steps"] == 3
    assert planner_cfg["step_cap"]["max_steps"] == 50

    # Building a governor must succeed with the filtered dict (no cross-agent bleed).
    build_governor(store.governance_config_for("researcher"), toy_price, store=store)
    build_governor(store.governance_config_for("planner"), toy_price, store=store)
    store.close()


def test_governance_config_excludes_other_agent_only_policies(tmp_path):
    store = Store(str(tmp_path / "gov2.db"), auto_seed=False)
    store.upsert_policy_instance(
        PolicyInstance(
            id="only-writer",
            template="step_cap",
            params={"max_steps": 7},
            agent="writer",
        )
    )
    planner_pols = store.governance_config_for("planner")["governance"]["policies"]
    writer_pols = store.governance_config_for("writer")["governance"]["policies"]
    assert "step_cap" not in planner_pols
    assert writer_pols["step_cap"]["max_steps"] == 7
    store.close()
