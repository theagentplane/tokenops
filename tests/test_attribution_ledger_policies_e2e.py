"""E2E: registration → attribution → ledger → policy enforcement.

Proves the three layers work together on the governed native path:
  1. Trace dims registered and resolved into Attribution on each crossing
  2. Ledger accumulates steps, spend, and window entries
  3. Store-configured policy (step_cap) trips HALT
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from tokenops.chronicle import reset_session
from tokenops.control import ApplyControls, build_governor, build_attribution, Halt, wrap_complete
from tokenops.control.context import SpanContext, governance_scope, run_scope
from tokenops.control.ledger import RUN_TOTAL_BUDGET, LIFETIME, segment_key_for
from tokenops.control.models import PolicyInstance, RunRegistration
from tokenops.control.pricing import build_price_book
from tokenops.control.store import Store


def _fake_complete(provider, model, messages, max_output_tokens=None):
    from tokenops.providers.types import ModelResponse
    return ModelResponse(
        content='{"action": "search", "query": "pricing"}',
        input_tokens=820,
        output_tokens=45,
    )


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "e2e.db"))
    s.upsert_policy_instance(
        PolicyInstance(
            id="pi_step",
            template="step_cap",
            params={"max_steps": 3},
            agent="research",
        )
    )
    yield s
    s.close()


def test_attribution_ledger_and_policy_e2e_in_process(store):
    """Register → govern agent → assert attribution on ledger, spend, and HALT."""
    from tokenops.agents.research.native.agent import NativeResearchAgent
    from tokenops.config.schema import AgentServerConfig

    reg = store.register_run(
        RunRegistration(
            run_id="e2e-run-1",
            intent="f500_frontier",
            user_dims={"Country": "US", "IsFortune500": "true", "user_id": "alice"},
        )
    )
    attr = build_attribution(reg, service="research")

    assert attr.run_id == "e2e-run-1"
    assert attr.agent == "research"
    assert attr.user == "alice"
    assert attr.tags["intent"] == "f500_frontier"
    assert attr.tags["Country"] == "US"
    assert segment_key_for(attr, "tag", "intent") == "tag:intent=f500_frontier"
    assert segment_key_for(attr, "tag", "Country") == "tag:Country=US"
    assert segment_key_for(attr, "run") == "run:e2e-run-1"
    assert segment_key_for(attr, "agent") == "agent:research"

    cfg = store.governance_config_for("research")
    gov = build_governor(cfg, build_price_book(), ApplyControls())
    gov.ledger.open_run("e2e-run-1")

    governed = wrap_complete(
        gov, gov.controls, attr,
        provider="openai", model="gpt-4o-mini",
        dispatch=_fake_complete, service="research",
    )
    agent = NativeResearchAgent(AgentServerConfig(max_steps=20, satisfaction_threshold=2.0))

    reset_session().begin_trace("e2e-run-1")
    with run_scope(reg, SpanContext(span_id="span-root", service="research")):
        with governance_scope(gov, attr, provider="openai", model="gpt-4o-mini"):
            with pytest.raises(Halt) as exc:
                agent.run("Research pricing", "healthy", complete_fn=governed, service="research")

    assert "step" in exc.value.action.reason.lower()
    assert gov.ledger.is_halted("e2e-run-1")

    assert gov.ledger.step_count("e2e-run-1") >= 3
    cost = gov.ledger.cost_micros("e2e-run-1")
    assert cost > 0

    run_key = f"run:e2e-run-1"
    assert gov.ledger._spent[(RUN_TOTAL_BUDGET.budget_id, run_key, LIFETIME)] == cost

    window = gov.ledger.window("e2e-run-1")
    assert len(window) >= 3
    llm_steps = [s for s in window if s.node_type == "llm"]
    tool_steps = [s for s in window if s.node_type == "tool"]
    assert llm_steps and tool_steps
    assert llm_steps[0].tags.get("provider") == "openai"
    assert llm_steps[0].tags.get("model") == "gpt-4o-mini"
    assert llm_steps[-1].cum_spent_micros == cost


def test_attribution_ledger_policy_via_http(store, monkeypatch, tmp_path):
    """Full HTTP path: POST /v1/runs → POST /v1/tasks with store policy."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    db = str(tmp_path / "http.db")
    monkeypatch.setenv("TOKENOPS_DB", db)
    s = Store(db)
    s.upsert_policy_instance(
        PolicyInstance(id="pi", template="step_cap", params={"max_steps": 2}, agent="research")
    )
    s.close()

    from tokenops.agents.research.native import server as srv

    with patch.object(srv, "complete", _fake_complete):
        client = TestClient(srv.build_app())

        reg_resp = client.post(
            "/v1/runs",
            json={"intent": "demo_intent", "user_dims": {"Country": "DE", "user_id": "bob"}},
        )
        assert reg_resp.status_code == 201
        run_id = reg_resp.json()["run_id"]

        task_resp = client.post(
            "/v1/tasks",
            json={"task": "test task", "bench": {"corpus_profile": "healthy"}},
            headers={"X-TokenOps-Run-Id": run_id},
        )
        body = task_resp.json()
        assert task_resp.status_code == 200
        assert body["status"] == "halted"
        assert body["cost_micros"] > 0

        s2 = Store(db)
        reg = s2.resolve_run(run_id)
        assert reg.intent == "demo_intent"
        assert reg.user_dims["Country"] == "DE"

        rec = s2.get_run(run_id)
        assert rec.status == "halted"
        assert rec.steps >= 2
        assert rec.cost_micros > 0
        s2.close()
