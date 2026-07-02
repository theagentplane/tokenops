"""trajectory_hint policy — lookup, inject, and background index build."""

from __future__ import annotations

import time

import pytest

from tokenops.control import ActionKind, CallRequest, build_governor
from tokenops.control.core import BoundaryStep
from tokenops.control.models import RunRecord, RunRegistration
from tokenops.control.policies.trajectory_hint import build as build_trajectory_hint
from tokenops.control.trajectory.enqueue import enqueue_completed_run
from tokenops.control.trajectory.scope import input_hash, input_simhash, normalize_input, scope_key
from conftest import CollectingControls, FakeView, make_attr, toy_price

HINT_CFG = {
    "governance": {
        "budgets": [{"id": "run_llm_cap", "limit_micros": 1_000_000, "dimension": "run"}],
        "policies": {
            "trajectory_hint": {
                "enabled": True,
                "scope_dims": ["intent", "agent"],
                "max_age_days": 30,
                "max_entries_per_scope": 100,
                "simhash_threshold": 4,
                "min_steps": 2,
                "min_index_steps": 4,
                "sequence_only_max_steps": 6,
                "sequence_plus_pitfalls_max_steps": 12,
                "min_input_chars": 10,
            },
        },
    }
}


@pytest.fixture
def store(tmp_path):
    from tokenops.control.store import Store

    s = Store(str(tmp_path / "t.db"))
    yield s
    s.close()


def _tool_step(step: int = 1) -> BoundaryStep:
    return BoundaryStep(
        step=step, ts=float(step), node_type="tool", boundary_id="search",
        cum_spent_micros=500,
        input={"name": "search", "args": {"query": "pricing"}},
        output={"snippet": "ok"},
        signature="sig1", result_hash="rh1",
    )


def test_scope_key_from_registration():
    reg = RunRegistration(run_id="r1", intent="research", user_dims={"team": "growth"})
    assert scope_key(reg, "research", ["intent", "agent"]) == "agent=research|intent=research"
    assert "team=growth" in scope_key(reg, "research", ["intent", "agent", "team"])


def test_enqueue_skipped_when_disabled(store):
    reg = RunRegistration(run_id="r1", intent="demo")
    rec = RunRecord(
        run_id="r1", agent="research", status="completed", task="find pricing API docs",
        cost_micros=1000, steps=5,
    )
    assert not enqueue_completed_run(
        store, rec=rec, registration=reg, agent="research", window=[_tool_step()],
        policy_params={"enabled": False},
    )
    assert store._db.execute("SELECT COUNT(*) FROM trajectory_build_queue").fetchone()[0] == 0


def test_enqueue_and_drain_builds_index(store):
    reg = RunRegistration(run_id="run-a", intent="demo")
    task = "find pricing API documentation"
    rec = RunRecord(
        run_id="run-a", agent="research", status="completed", task=task,
        cost_micros=50_000, steps=4,
    )
    params = HINT_CFG["governance"]["policies"]["trajectory_hint"]
    assert enqueue_completed_run(
        store, rec=rec, registration=reg, agent="research",
        window=[_tool_step(), _tool_step(2)], policy_params=params,
    )
    assert store.drain_trajectory_build_queue(max_age_days=30) == 1

    sk = scope_key(reg, "research", ["intent", "agent"])
    hit = store.lookup_trajectory_index(
        scope_key=sk,
        input_hash=input_hash(task),
        input_simhash=0,
        max_age_days=30,
        simhash_threshold=4,
    )
    assert hit is not None
    assert hit["source_run_id"] == "run-a"
    assert "search" in hit["tool_sequence"]


def test_simhash_lookup_paraphrase(store):
    reg = RunRegistration(run_id="run-a", intent="demo")
    task = "research enterprise saas pricing models and subscription tiers"
    paraphrase = "enterprise research saas pricing models and subscription tiers"
    assert input_hash(task) != input_hash(paraphrase)

    rec = RunRecord(
        run_id="run-a", agent="research", status="completed", task=task,
        cost_micros=50_000, steps=3,
    )
    params = HINT_CFG["governance"]["policies"]["trajectory_hint"]
    enqueue_completed_run(
        store, rec=rec, registration=reg, agent="research",
        window=[_tool_step()], policy_params=params,
    )
    store.drain_trajectory_build_queue(max_age_days=30)

    sk = scope_key(reg, "research", ["intent", "agent"])
    from tokenops.control.trajectory.scope import input_simhash as ish, simhash_as_sqlite

    hit = store.lookup_trajectory_index(
        scope_key=sk,
        input_hash=input_hash(paraphrase),
        input_simhash=simhash_as_sqlite(ish(paraphrase)),
        max_age_days=30,
        simhash_threshold=4,
    )
    assert hit is not None
    assert hit["match"] == "simhash"


def test_pre_call_injects_on_step_zero(store):
    reg = RunRegistration(run_id="prior", intent="demo")
    task = "find enterprise pricing limits"
    rec = RunRecord(
        run_id="prior", agent="research", status="completed", task=task,
        cost_micros=40_000, steps=5,
    )
    params = HINT_CFG["governance"]["policies"]["trajectory_hint"]
    enqueue_completed_run(
        store, rec=rec, registration=reg, agent="research",
        window=[_tool_step()], policy_params=params,
    )
    store.drain_trajectory_build_queue(max_age_days=30)

    controls = CollectingControls()
    gov = build_governor(HINT_CFG, toy_price, controls, store=store)
    gov.ledger.open_run("run-new")
    store.create_run(
        RunRecord(run_id="run-new", agent="research", status="running", task=task,
                  started_at=time.time()),
    )

    attr = make_attr(run_id="run-new", agent="research", tags={"intent": "demo"})
    gov.pre_call(CallRequest(
        attr=attr, provider="openai", model="gpt-4o-mini", primary_agent_turn=True,
    ))
    injects = controls.of_kind(ActionKind.INJECT)
    assert len(injects) == 1
    assert "trajectory hint" in (injects[0].inject_message or "").lower()

    # edge-trigger: second pre_call on step 0 state should not double-inject
    gov.pre_call(CallRequest(attr=attr, provider="openai", model="gpt-4o-mini"))
    assert len(controls.of_kind(ActionKind.INJECT)) == 1


def test_no_inject_when_step_count_nonzero(store):
    controls = CollectingControls()
    gov = build_governor(HINT_CFG, toy_price, controls, store=store)
    gov.ledger.open_run("run-new")
    store.create_run(
        RunRecord(run_id="run-new", agent="research", status="running",
                  task="find enterprise pricing limits", started_at=time.time()),
    )
    attr = make_attr(run_id="run-new", agent="research", tags={"intent": "demo"})
    view = FakeView(_steps=2)
    det, _ = build_trajectory_hint(store, enabled=True, max_age_days=30)
    assert det.pre_call(
        CallRequest(attr=attr, provider="openai", model="gpt-4o-mini"), view,
    ) is None


def test_trajectory_hint_requires_store():
    with pytest.raises(ValueError, match="requires store"):
        build_governor(HINT_CFG, toy_price)


def test_skip_inject_when_index_steps_below_min_index_steps(store):
    reg = RunRegistration(run_id="prior", intent="demo")
    task = "find enterprise pricing limits today"
    rec = RunRecord(
        run_id="prior", agent="research", status="completed", task=task,
        cost_micros=40_000, steps=2,
    )
    params = {**HINT_CFG["governance"]["policies"]["trajectory_hint"], "min_index_steps": 4}
    enqueue_completed_run(
        store, rec=rec, registration=reg, agent="research",
        window=[_tool_step()], policy_params=params,
    )
    store.drain_trajectory_build_queue(max_age_days=30)

    controls = CollectingControls()
    cfg = {
        "governance": {
            "budgets": HINT_CFG["governance"]["budgets"],
            "policies": {"trajectory_hint": params},
        }
    }
    gov = build_governor(cfg, toy_price, controls, store=store)
    gov.ledger.open_run("run-new")
    store.create_run(
        RunRecord(run_id="run-new", agent="research", status="running", task=task,
                  started_at=time.time()),
    )
    attr = make_attr(run_id="run-new", agent="research", tags={"intent": "demo"})
    gov.pre_call(CallRequest(attr=attr, provider="openai", model="gpt-4o-mini", primary_agent_turn=True))
    assert controls.of_kind(ActionKind.INJECT) == []


def test_tiered_hint_format():
    from tokenops.control.trajectory.hint import TrajectoryHit, format_hint, hint_tier_for

    hit = TrajectoryHit(
        source_run_id="run-x",
        step_count=5,
        cost_micros=100_000,
        tool_sequence="search → paginate",
        step_summary="Tool sequence (2 calls): search → paginate.\nLLM steps: 3.",
        match="exact",
    )
    assert hint_tier_for(5) == "sequence_only"
    short = format_hint(hit, tier="sequence_only")
    assert "search → paginate" in short
    assert "LLM steps" not in short

    hit_long = TrajectoryHit(
        source_run_id="run-y", step_count=14, cost_micros=200_000,
        tool_sequence="a → b", step_summary="Full summary line.", match="simhash",
    )
    assert hint_tier_for(14) == "full"
    full = format_hint(hit_long, tier="full")
    assert "Full summary line" in full
