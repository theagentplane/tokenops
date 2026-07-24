"""Store — CRUD, fail-closed validation, and governance_config_for round-trip."""

from __future__ import annotations

import pytest

from conftest import toy_price
from tokenops.control import build_governor
from tokenops.control.ledger import LIFETIME, RUN_TOTAL_BUDGET
from tokenops.control.models import (
    BudgetSpec,
    PolicyInstance,
    RunRecord,
    RunRegistration,
    Segment,
)
from tokenops.control.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    yield s
    s.close()


def test_segment_budget_policy_crud(store):
    store.upsert_segment(Segment(id="seg_run", name="per run", dimension="run"))
    store.upsert_budget(BudgetSpec(id="run_llm_cap", limit_micros=20_000, dimension="run"))
    store.upsert_policy_instance(
        PolicyInstance(id="pi1", template="cost_budget", budget_id="run_llm_cap", agent="research")
    )
    assert store.get_segment("seg_run").dimension == "run"
    assert store.get_budget("run_llm_cap").limit_micros == 20_000
    assert store.get_policy_instance("pi1").template == "cost_budget"
    assert len(store.list_policy_instances()) == 1


def test_unknown_template_fails_closed(store):
    with pytest.raises(ValueError, match="unknown policy template"):
        store.upsert_policy_instance(PolicyInstance(id="x", template="nonsense"))


def test_governance_config_builds_a_governor(store):
    store.upsert_budget(BudgetSpec(id="run_llm_cap", limit_micros=20_000, dimension="run"))
    store.upsert_policy_instance(
        PolicyInstance(id="pi1", template="cost_budget", budget_id="run_llm_cap", agent="research")
    )
    store.upsert_policy_instance(
        PolicyInstance(id="pi2", template="step_cap", params={"max_steps": 5})
    )  # agent=None → all
    cfg = store.governance_config_for("research")
    # the assembled dict is exactly build_governor's input shape
    gov = build_governor(cfg, toy_price)
    assert set(gov._policy_by_name) == {"cost_budget", "step_cap"}
    assert gov.ledger.budget_left("run_llm_cap", "run:run-1") == 20_000


def test_agent_scoping(store):
    store.upsert_policy_instance(
        PolicyInstance(id="pi", template="step_cap", params={"max_steps": 3}, agent="summarize")
    )
    assert store.governance_config_for("research")["governance"]["policies"] == {}
    assert "step_cap" in store.governance_config_for("summarize")["governance"]["policies"]


def test_run_records_and_problematic_filter(store):
    store.create_run(RunRecord(run_id="r1", agent="research", status="completed", cost_micros=500))
    store.create_run(
        RunRecord(
            run_id="r2",
            agent="research",
            status="halted",
            halt_reason="budget exhausted",
            detector="cost_budget",
            cost_micros=20_000,
        )
    )
    store.update_run("r1", ended_at=123.0)
    assert store.get_run("r1").ended_at == 123.0
    assert len(store.list_runs()) == 2
    problematic = store.list_runs(problematic_only=True)
    assert [r.run_id for r in problematic] == ["r2"]
    assert problematic[0].halt_reason == "budget exhausted"


def test_register_run_creates_dashboard_row(store):
    """Registration alone must surface on the Admin Dashboard (list_runs / get_run)."""
    store.register_run(
        RunRegistration(
            run_id="reg-only",
            intent="summarize",
            user_dims={"team": "growth"},
        )
    )
    got = store.get_run("reg-only")
    assert got is not None
    assert got.agent == "summarize"
    assert got.status == "running"
    assert got.task == "summarize"
    assert got.dims == {"team": "growth"}
    assert got.cost_micros == 0
    listed = store.list_runs()
    assert [r.run_id for r in listed] == ["reg-only"]

    store.ledger_add_spent(RUN_TOTAL_BUDGET.budget_id, "run:reg-only", LIFETIME, 12_345)
    assert store.get_run("reg-only").cost_micros == 12_345
    assert store.list_runs()[0].cost_micros == 12_345

    # Explicit create_run after register remains REPLACE-safe.
    store.create_run(
        RunRecord(
            run_id="reg-only",
            agent="summarize",
            status="completed",
            cost_micros=99,
            dims={"team": "growth"},
            task="summarize",
        )
    )
    after = store.get_run("reg-only")
    assert after.status == "completed"
    assert after.cost_micros == 12_345  # ledger still overlays

    store.ledger_mark_halted("reg-only", reason="budget exhausted")
    halted = store.get_run("reg-only")
    assert halted.status == "halted"
    assert halted.halt_reason == "budget exhausted"

    store.ledger_clear_halt("reg-only")
    cleared = store.get_run("reg-only")
    assert cleared.halt_reason is None
    assert cleared.status == "halted"  # clear does not invent a new status

    store.register_run(RunRegistration(run_id="no-intent"))
    assert store.get_run("no-intent").agent == "agent"
    assert store.get_run("no-intent").task is None


def test_seed_default_governance_if_empty(tmp_path, monkeypatch):
    monkeypatch.delenv("TOKENOPS_SKIP_GOVERNANCE_SEED", raising=False)
    s = Store(str(tmp_path / "seed.db"), auto_seed=False)
    governance = {
        "budgets": [{"id": "run_llm_cap", "limit_micros": 2_000_000, "dimension": "run"}],
        "policies": {
            "cost_budget": {"budget": "run_llm_cap"},
            "step_cap": {"max_steps": 20},
        },
    }
    assert s.seed_default_governance_if_empty(governance) is True
    assert s.get_budget("run_llm_cap").limit_micros == 2_000_000
    assert len(s.list_policy_instances()) == 2
    assert s.seed_default_governance_if_empty(governance) is False  # idempotent
    cfg = s.governance_config_for("research")
    gov = build_governor(cfg, toy_price)
    assert set(gov._policy_by_name) == {"cost_budget", "step_cap"}
    s.close()


def test_clear_and_reseed_governance(tmp_path):
    s = Store(str(tmp_path / "reset.db"), auto_seed=False)
    s.upsert_budget(BudgetSpec(id="custom", limit_micros=100, dimension="run"))
    s.upsert_policy_instance(PolicyInstance(id="pi", template="step_cap", params={"max_steps": 1}))
    s.create_run(RunRecord(run_id="r1", agent="research", status="completed"))
    governance = {
        "budgets": [{"id": "run_llm_cap", "limit_micros": 2_000_000, "dimension": "run"}],
        "policies": {"cost_budget": {"budget": "run_llm_cap"}},
    }
    s.reseed_governance(governance)
    assert s.get_budget("custom") is None
    assert s.get_budget("run_llm_cap") is not None
    assert len(s.list_policy_instances()) == 1
    assert len(s.list_runs()) == 1  # runs preserved
    s.clear_all()
    assert len(s.list_runs()) == 0
    s.close()


def test_run_dims_roundtrip_grouping_and_tag_keys(store):
    store.create_run(
        RunRecord(
            run_id="a",
            agent="research",
            status="completed",
            cost_micros=300,
            dims={"team": "growth", "Country": "US"},
        )
    )
    store.create_run(
        RunRecord(
            run_id="b", agent="research", status="completed", cost_micros=100, dims={"team": "core"}
        )
    )
    assert store.get_run("a").dims == {"team": "growth", "Country": "US"}
    assert set(store.run_tag_keys()) == {"team", "Country"}
    # group cost by the custom 'team' tag (what the dashboard does)
    by_team: dict[str, int] = {}
    for r in store.list_runs():
        by_team[r.dims.get("team", "—")] = by_team.get(r.dims.get("team", "—"), 0) + r.cost_micros
    assert by_team == {"growth": 300, "core": 100}


def test_dims_migration_on_legacy_db(tmp_path):
    import sqlite3

    # simulate a pre-dims runs table, then open with Store (which should migrate)
    db = str(tmp_path / "legacy.db")
    con = sqlite3.connect(db)
    con.executescript(
        "CREATE TABLE runs (run_id TEXT PRIMARY KEY, agent TEXT NOT NULL, "
        "status TEXT NOT NULL, parent_run TEXT, halt_reason TEXT, detector TEXT, "
        "cost_micros INTEGER DEFAULT 0, steps INTEGER DEFAULT 0, "
        "started_at REAL DEFAULT 0, ended_at REAL, task TEXT);"
    )
    con.execute("INSERT INTO runs(run_id, agent, status) VALUES ('old','research','completed')")
    con.commit()
    con.close()
    s = Store(db, auto_seed=False)
    assert s.get_run("old").dims == {}  # migrated column, default empty
    s.create_run(RunRecord(run_id="new", agent="research", dims={"team": "x"}))
    assert s.get_run("new").dims == {"team": "x"}
    s.close()
