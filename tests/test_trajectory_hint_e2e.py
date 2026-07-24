"""E2E: prior run indexed → second run gets trajectory hint on first LLM dispatch."""

from __future__ import annotations

import time

import pytest

from conftest import toy_price
from tokenops.control import ApplyControls, build_governor, wrap_complete
from tokenops.control.attribution import _build_attribution
from tokenops.control.core import BoundaryStep, Observation, Usage
from tokenops.control.models import PolicyInstance, RunRecord, RunRegistration
from tokenops.control.trajectory.enqueue import enqueue_completed_run
from tokenops.control.trajectory.scope import input_hash

HINT_GOVERNANCE = {
    "governance": {
        "budgets": [{"id": "run_llm_cap", "limit_micros": 5_000_000, "dimension": "run"}],
        "policies": {
            "trajectory_hint": {
                "enabled": True,
                "scope_dims": ["intent", "agent"],
                "max_age_days": 30,
                "max_entries_per_scope": 100,
                "simhash_threshold": 4,
                "min_steps": 2,
                "min_input_chars": 10,
            },
        },
    }
}

TASK = "research enterprise saas pricing models and subscription tiers"
PARAPHRASE = "enterprise research saas pricing models and subscription tiers"


def _fake_dispatch(calls: list):
    def dispatch(provider, model, messages, max_output_tokens=None):
        calls.append(
            {"model": model, "messages": list(messages), "max_output_tokens": max_output_tokens}
        )
        from tokenops.providers.types import ModelResponse

        return ModelResponse(content="ok", input_tokens=10, output_tokens=5)

    return dispatch


def _tool_step(step: int = 1) -> BoundaryStep:
    return BoundaryStep(
        step=step,
        ts=float(step),
        node_type="tool",
        boundary_id="search",
        cum_spent_micros=12_000,
        input={"name": "search", "args": {"query": "pricing"}},
        output={"snippet": "tier list"},
        signature="sig1",
        result_hash="rh1",
    )


@pytest.fixture
def store(tmp_path):
    from tokenops.control.store import Store

    s = Store(str(tmp_path / "hint_e2e.db"))
    s.upsert_policy_instance(
        PolicyInstance(
            id="pi_traj",
            template="trajectory_hint",
            params=HINT_GOVERNANCE["governance"]["policies"]["trajectory_hint"],
            agent="research",
        )
    )
    yield s
    s.close()


def test_trajectory_hint_end_to_end_via_wrap_complete(store):
    """Run A completes and is indexed; Run B's first governed LLM call receives the hint."""
    # ---- Run A: complete, index (sync drain — no daemon thread in tests) ----
    reg_a = store.register_run(
        RunRegistration(run_id="run-a", intent="pricing_research", user_dims={"user_id": "alice"}),
    )
    rec_a = RunRecord(
        run_id="run-a",
        agent="research",
        status="completed",
        task=TASK,
        cost_micros=120_000,
        steps=4,
        started_at=time.time(),
        ended_at=time.time(),
    )
    store.create_run(rec_a)
    window_a = [_tool_step(1), _tool_step(2)]
    assert enqueue_completed_run(
        store,
        rec=rec_a,
        registration=reg_a,
        agent="research",
        window=window_a,
        policy_params=HINT_GOVERNANCE["governance"]["policies"]["trajectory_hint"],
    )
    assert store.drain_trajectory_build_queue(max_age_days=30) == 1

    # ---- Run B: cold start, same intent/agent, paraphrased task ----
    reg_b = store.register_run(
        RunRegistration(run_id="run-b", intent="pricing_research", user_dims={"user_id": "bob"}),
    )
    attr_b = _build_attribution(reg_b, service="research")
    store.create_run(
        RunRecord(
            run_id="run-b",
            agent="research",
            status="running",
            task=PARAPHRASE,
            started_at=time.time(),
        ),
    )

    assert input_hash(TASK) != input_hash(PARAPHRASE)

    gov = build_governor(HINT_GOVERNANCE, toy_price, ApplyControls(), store=store)
    gov.ledger.open_run("run-b")

    calls: list = []
    governed = wrap_complete(
        gov,
        gov.controls,
        attr_b,
        provider="openai",
        model="gpt-4o-mini",
        dispatch=_fake_dispatch(calls),
        service="research",
    )

    governed("openai", "gpt-4o-mini", [{"role": "user", "content": PARAPHRASE}])

    assert len(calls) == 1
    messages = calls[0]["messages"]
    assert messages[0] == {"role": "user", "content": PARAPHRASE}
    hint_turn = messages[-1]
    assert hint_turn["role"] == "user"
    assert "trajectory hint" in hint_turn["content"].lower()
    assert "run-a" in hint_turn["content"]
    assert "search" in hint_turn["content"]
    assert gov.controls.carry == []  # consumed by wrap


def test_trajectory_hint_no_hint_on_cold_start(store):
    """First-ever run for a task gets no hint injected."""
    reg = store.register_run(
        RunRegistration(
            run_id="run-cold", intent="pricing_research", user_dims={"user_id": "carol"}
        ),
    )
    attr = _build_attribution(reg, service="research")
    store.create_run(
        RunRecord(
            run_id="run-cold",
            agent="research",
            status="running",
            task="brand new unique task about widget inventory",
            started_at=time.time(),
        ),
    )

    gov = build_governor(HINT_GOVERNANCE, toy_price, ApplyControls(), store=store)
    gov.ledger.open_run("run-cold")

    calls: list = []
    governed = wrap_complete(
        gov,
        gov.controls,
        attr,
        provider="openai",
        model="gpt-4o-mini",
        dispatch=_fake_dispatch(calls),
        service="research",
    )
    governed(
        "openai",
        "gpt-4o-mini",
        [{"role": "user", "content": "brand new unique task about widget inventory"}],
    )

    assert len(calls) == 1
    assert len(calls[0]["messages"]) == 1  # no hint turn appended


def test_trajectory_hint_not_reinjected_on_second_llm_call(store):
    """Hint fires once at step 0; the second LLM call in the same run has no hint."""
    reg_a = store.register_run(
        RunRegistration(run_id="run-a2", intent="pricing_research", user_dims={"user_id": "alice"}),
    )
    rec_a = RunRecord(
        run_id="run-a2",
        agent="research",
        status="completed",
        task=TASK,
        cost_micros=120_000,
        steps=4,
        started_at=time.time(),
        ended_at=time.time(),
    )
    store.create_run(rec_a)
    enqueue_completed_run(
        store,
        rec=rec_a,
        registration=reg_a,
        agent="research",
        window=[_tool_step()],
        policy_params=HINT_GOVERNANCE["governance"]["policies"]["trajectory_hint"],
    )
    store.drain_trajectory_build_queue(max_age_days=30)

    reg_b = store.register_run(
        RunRegistration(run_id="run-b2", intent="pricing_research", user_dims={"user_id": "bob"}),
    )
    attr_b = _build_attribution(reg_b, service="research")
    store.create_run(
        RunRecord(
            run_id="run-b2", agent="research", status="running", task=TASK, started_at=time.time()
        ),
    )

    gov = build_governor(HINT_GOVERNANCE, toy_price, ApplyControls(), store=store)
    gov.ledger.open_run("run-b2")

    calls: list = []
    governed = wrap_complete(
        gov,
        gov.controls,
        attr_b,
        provider="openai",
        model="gpt-4o-mini",
        dispatch=_fake_dispatch(calls),
        service="research",
    )

    governed("openai", "gpt-4o-mini", [{"role": "user", "content": TASK}])
    assert len(calls[0]["messages"]) == 2  # task + hint

    # Record one LLM step so step_count > 0 for the next call.
    gov.observe(
        Observation(
            attr=attr_b,
            node_type="llm",
            boundary_id="research.chat",
            ts=time.time(),
            provider="openai",
            model="gpt-4o-mini",
            usage=Usage(input=10, output=5),
            output={"text": "ok"},
        )
    )

    governed("openai", "gpt-4o-mini", [{"role": "user", "content": "follow up"}])
    assert len(calls[1]["messages"]) == 1  # no second hint
