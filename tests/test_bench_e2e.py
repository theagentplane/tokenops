"""End-to-end on the real A2A research bench (FastAPI TestClient).

Drives the full live path — entry registers run on task → per-run governor → actuators →
RunRecord — for four policies. Only the model call and the search tool are faked (no API
key, no network); the server, governor, ledger, store, and agent loop are all real.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from bench.agents.research.tools import core as search_core
from bench.agents.research.tools.core import SearchResult
from tokenops.control.models import BudgetSpec, PolicyInstance
from tokenops.control.store import Store
from tokenops.providers.types import ModelResponse


def _search(query, profile="healthy"):
    return SearchResult(query=query, snippet="small snippet", completeness=0.2, source="test")


def _run(client, *, intent="demo", user_dims=None):
    """UI path: POST /v1/tasks without run_id — research registers the run."""
    payload = {
        "task": "research pricing",
        "intent": intent,
        "user_dims": user_dims or {"user_id": "alice"},
        "bench": {"corpus_profile": "healthy"},
    }
    resp = client.post("/v1/tasks", json=payload)
    return resp.json()


def _client(monkeypatch, tmp_path, policies, budgets=(), model=None):
    db = str(tmp_path / "bench.db")
    monkeypatch.setenv("TOKENOPS_DB", db)
    monkeypatch.delenv("TOKENOPS_URL", raising=False)
    monkeypatch.setenv("TOKENOPS_EMBEDDED", "1")
    s = Store(db)
    for b in budgets:
        s.upsert_budget(b)
    for pi in policies:
        s.upsert_policy_instance(pi)
    s.close()
    monkeypatch.setattr(search_core, "search", _search)
    from bench.agents.research.native import server as srv
    if model is not None:
        monkeypatch.setattr(srv, "complete", model)

    async def _fake_delegate(*a, **k):  # summarize server isn't running in-test
        from bench.agents.types import TokenUsage
        return ("summary", TokenUsage(), [], 0)

    monkeypatch.setattr(srv, "delegate_summarize", _fake_delegate)
    return srv, TestClient(srv.build_app())


def _always_search(provider, model, messages, max_output_tokens=None, **kw):
    return ModelResponse(content='{"action": "search", "query": "pricing"}', input_tokens=820, output_tokens=45)


# 1) step_cap → HALT
def test_step_cap_halts(monkeypatch, tmp_path):
    srv, client = _client(monkeypatch, tmp_path,
                          [PolicyInstance(id="p", template="step_cap", params={"max_steps": 2}, agent="research")],
                          model=_always_search)
    body = _run(client)
    assert body["status"] == "halted" and "step" in body["halt_reason"].lower()
    assert body["cost_micros"] > 0


# 2) cost_budget → HALT
def test_cost_budget_halts(monkeypatch, tmp_path):
    srv, client = _client(
        monkeypatch, tmp_path,
        [PolicyInstance(id="p", template="cost_budget", budget_id="cap", agent="research")],
        budgets=[BudgetSpec(id="cap", limit_micros=250, dimension="run")],  # ~150 micros/call → halts on 2nd
        model=_always_search,
    )
    body = _run(client)
    assert body["status"] == "halted" and "budget" in body["halt_reason"].lower()


# 3) output_runaway via streaming → CANCEL + RETRY → run completes
def test_cancel_retry_streaming(monkeypatch, tmp_path):
    monkeypatch.setenv("TOKENOPS_STREAM", "1")
    calls = {"n": 0}

    def fake_stream(provider, model, messages, *, max_output_tokens=None, frequency_penalty=None, presence_penalty=None):
        i = calls["n"]; calls["n"] += 1
        if i < 2:                       # degenerate — gets cancelled mid-stream
            for _ in range(100):
                yield "loop "
        else:                           # clean decision ends the agent loop
            yield '{"action": "finish"}'

    srv, client = _client(monkeypatch, tmp_path,
                          [PolicyInstance(id="p", template="output_runaway",
                                          params={"repeats": 4, "max_retries": 2}, agent="research")])
    monkeypatch.setattr(srv, "stream_complete", fake_stream)
    body = _run(client)
    assert body["status"] == "completed"   # CANCEL + RETRY recovered, no crash
    assert calls["n"] == 3                  # 2 cancelled streams + 1 clean retry
    assert body["cost_micros"] > 0


# 4) tool_output_cap deep swap → the oversized result is replaced by the descriptor
def test_tool_output_cap_substitutes_result(monkeypatch, tmp_path):
    big = "x" * 60_000

    def search_then_finish(provider, model, messages, max_output_tokens=None, **kw):
        # search on the first call, finish on the second
        n = search_then_finish.n = getattr(search_then_finish, "n", 0) + 1
        action = "search" if n == 1 else "finish"
        return ModelResponse(content=f'{{"action": "{action}", "query": "pricing"}}',
                             input_tokens=100, output_tokens=10)

    srv, client = _client(monkeypatch, tmp_path,
                          [PolicyInstance(id="p", template="tool_output_cap",
                                          params={"cap_tokens": 1000}, agent="research")],
                          model=search_then_finish)
    # patch the search AFTER _client (which sets a small default) so the result is oversized
    monkeypatch.setattr(search_core, "search",
                        lambda q, profile="healthy": SearchResult(query=q, snippet=big, completeness=0.2, source="test"))
    body = _run(client)
    assert body["status"] == "completed"
    snippets = [f["snippet"] for f in body["findings"]]
    assert any(s.startswith("TOOL OUTPUT OFFLOADED") for s in snippets)  # deep swap landed in context


# 5) custom tag flows onto the persisted RunRecord (segmentation backbone)
def test_run_dims_persisted_for_segmentation(monkeypatch, tmp_path):
    import os
    from tokenops.control.store import Store
    srv, client = _client(monkeypatch, tmp_path,
                          [PolicyInstance(id="p", template="step_cap", params={"max_steps": 2}, agent="research")],
                          model=_always_search)
    body = _run(client, user_dims={"user_id": "alice", "team": "growth"})
    run_id = body["run_id"]
    s = Store(os.environ["TOKENOPS_DB"], auto_seed=False)
    rec = s.get_run(run_id)
    assert rec.dims.get("team") == "growth"          # custom tag persisted on the run
    assert "team" in s.run_tag_keys()                # dashboard can group by it
    s.close()
