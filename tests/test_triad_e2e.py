"""End-to-end triad bench (Planner → Researcher → Writer) with mocked LLMs.

Drives the real FastAPI handlers, shared Store/ledger, wrap_complete, crossing
hook, and A2A delegates. Only ``complete`` and the search tool are faked.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from bench.agents.research.tools import core as search_core
from bench.agents.research.tools.core import SearchResult
from bench.a2a import server as a2a_server
from tokenops.control.client import ControlPlaneClient
from tokenops.control.context import RUN_ID_HEADER
from tokenops.control.models import BudgetSpec, PolicyInstance
from tokenops.control.store import Store
from tokenops.providers.types import ModelResponse


def _search(query, profile="healthy"):
    return SearchResult(
        query=query,
        snippet=f"Fact about {query}: mid-market CRM seats average $80/user/mo.",
        completeness=0.9,
        source="test",
    )


def _plan_then_done(provider, model, messages, max_output_tokens=None, **kw):
    content = json.dumps({
        "questions": ["What is mid-market CRM pricing?", "Seat vs usage pricing?"],
        "outline": ["Pricing models", "Typical ranges", "Takeaways"],
    })
    return ModelResponse(content=content, input_tokens=120, output_tokens=40)


def _research_search_then_finish(provider, model, messages, max_output_tokens=None, **kw):
    n = _research_search_then_finish.n = getattr(_research_search_then_finish, "n", 0) + 1
    if n == 1:
        return ModelResponse(
            content='{"action": "search", "query": "mid-market CRM pricing"}',
            input_tokens=100,
            output_tokens=20,
        )
    return ModelResponse(content='{"action": "finish"}', input_tokens=80, output_tokens=10)


def _always_search(provider, model, messages, max_output_tokens=None, **kw):
    return ModelResponse(
        content='{"action": "search", "query": "pricing"}',
        input_tokens=820,
        output_tokens=45,
    )


def _write_answer(provider, model, messages, max_output_tokens=None, **kw):
    return ModelResponse(
        content="Mid-market CRM pricing typically runs $50–$120 per seat per month.",
        input_tokens=200,
        output_tokens=60,
    )


def _seed(tmp_path, monkeypatch, policies, budgets=()):
    db = str(tmp_path / "triad.db")
    monkeypatch.setenv("TOKENOPS_DB", db)
    monkeypatch.setenv("TOKENOPS_EMBEDDED", "1")
    monkeypatch.delenv("TOKENOPS_URL", raising=False)
    monkeypatch.setenv("TOKENOPS_CONFIG", "src/tokenops/config/triad.yaml")
    monkeypatch.setenv("SEARCH_BACKEND", "corpus")
    # Avoid YAML seed so test policies are the only ones present.
    s = Store(db, auto_seed=False)
    for b in budgets:
        s.upsert_budget(b)
    for pi in policies:
        s.upsert_policy_instance(pi)
    s.close()
    monkeypatch.setattr(search_core, "search", _search)
    return db


def _wire_apps(monkeypatch):
    from bench.triad.planner import server as planner_srv
    from bench.triad.researcher import server as researcher_srv
    from bench.triad.writer import server as writer_srv

    monkeypatch.setattr(planner_srv, "complete", _plan_then_done)
    monkeypatch.setattr(researcher_srv, "complete", _research_search_then_finish)
    monkeypatch.setattr(writer_srv, "complete", _write_answer)

    planner = TestClient(planner_srv.build_app())
    researcher = TestClient(researcher_srv.build_app())
    writer = TestClient(writer_srv.build_app())

    clients = {
        "http://localhost:8011": planner,
        "http://localhost:8012": researcher,
        "http://localhost:8013": writer,
    }

    def _route_post(url, payload, *, headers=None, timeout=300.0):
        base = url.rstrip("/")
        client = clients[base]
        health = client.get("/health")
        assert health.status_code == 200
        resp = client.post("/v1/tasks", json=payload, headers=headers or {})
        assert resp.status_code == 200, resp.text
        return resp.json()

    async def _route_post_async(url, payload, *, headers=None, timeout=300.0):
        return _route_post(url, payload, headers=headers, timeout=timeout)

    monkeypatch.setattr(a2a_server, "post_task_sync", _route_post)
    monkeypatch.setattr(a2a_server, "post_task", _route_post_async)
    # triad.client imports post_task / post_task_sync by name — patch there too
    import bench.triad.client as triad_client

    monkeypatch.setattr(triad_client, "post_task", _route_post_async)
    monkeypatch.setattr(triad_client, "post_task_sync", _route_post)

    return planner, researcher, writer


def test_triad_pipeline_completes_with_ledger(monkeypatch, tmp_path):
    _seed(
        tmp_path,
        monkeypatch,
        [
            PolicyInstance(id="p-step", template="step_cap", params={"max_steps": 40}),
            PolicyInstance(
                id="p-budget",
                template="cost_budget",
                budget_id="run_llm_cap",
            ),
        ],
        budgets=[BudgetSpec(id="run_llm_cap", limit_micros=2_000_000, dimension="run")],
    )
    _research_search_then_finish.n = 0
    planner, _researcher, _writer = _wire_apps(monkeypatch)

    reg = ControlPlaneClient.from_env().register_run(
        intent="triad-demo", user_dims={"user_id": "alice"},
    )
    run_id = reg["run_id"]
    resp = planner.post(
        "/v1/tasks",
        json={"task": "Explain mid-market CRM pricing", "bench": {"corpus_profile": "healthy"}},
        headers={RUN_ID_HEADER: run_id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "completed"
    assert body["run_id"] == run_id
    assert body["answer"]
    assert body["questions"]
    assert body["findings"]
    assert body["cost_micros"] > 0
    assert any(s["agent"] == "researcher" and s["action"] == "search" for s in body["steps"])
    assert any(s["agent"] == "writer" for s in body["steps"])

    store = Store(tmp_path / "triad.db", auto_seed=False)
    rec = store.get_run(run_id)
    assert rec is not None
    assert rec.status == "completed"
    assert rec.cost_micros > 0
    store.close()


def test_triad_step_cap_halts(monkeypatch, tmp_path):
    _seed(
        tmp_path,
        monkeypatch,
        [PolicyInstance(id="p", template="step_cap", params={"max_steps": 2}, agent="researcher")],
    )
    monkeypatch.setattr(
        search_core,
        "search",
        lambda q, profile="healthy": SearchResult(
            query=q, snippet="tiny", completeness=0.2, source="test",
        ),
    )
    from bench.triad.researcher import server as researcher_srv

    monkeypatch.setattr(researcher_srv, "complete", _always_search)
    researcher = TestClient(researcher_srv.build_app())

    reg = ControlPlaneClient.from_env().register_run(intent="halt-direct")
    run_id = reg["run_id"]
    resp = researcher.post(
        "/v1/tasks",
        json={
            "task": "pricing",
            "questions": ["q1", "q2"],
            "bench": {"corpus_profile": "healthy"},
        },
        headers={RUN_ID_HEADER: run_id},
    )
    body = resp.json()
    assert body["status"] == "halted"
    assert "step" in (body.get("halt_reason") or "").lower()
    assert body["cost_micros"] > 0


def test_triad_cost_budget_halts_on_researcher(monkeypatch, tmp_path):
    _seed(
        tmp_path,
        monkeypatch,
        [
            PolicyInstance(
                id="p",
                template="cost_budget",
                budget_id="cap",
                agent="researcher",
            ),
        ],
        budgets=[BudgetSpec(id="cap", limit_micros=250, dimension="run")],
    )
    # Keep the loop alive: low completeness so satisfaction_threshold never trips.
    monkeypatch.setattr(
        search_core,
        "search",
        lambda q, profile="healthy": SearchResult(
            query=q, snippet="tiny", completeness=0.2, source="test",
        ),
    )
    from bench.triad.researcher import server as researcher_srv

    monkeypatch.setattr(researcher_srv, "complete", _always_search)
    researcher = TestClient(researcher_srv.build_app())

    reg = ControlPlaneClient.from_env().register_run(intent="budget-halt")
    run_id = reg["run_id"]
    resp = researcher.post(
        "/v1/tasks",
        json={
            "task": "pricing",
            "questions": ["q1"],
            "bench": {"corpus_profile": "healthy"},
        },
        headers={RUN_ID_HEADER: run_id},
    )
    body = resp.json()
    assert body["status"] == "halted"
    assert "budget" in (body.get("halt_reason") or "").lower()
