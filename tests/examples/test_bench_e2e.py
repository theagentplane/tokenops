"""End-to-end on the real A2A research bench (FastAPI TestClient) against a real,
in-process control plane (real TCP port — tokenops#118: tokenops has no ledger of
its own, so this is the only kind of "real" left to test against).

Drives the full live path — entry registers run on task → per-run governor (reading
policies the *plane* was configured with over its own HTTP API) → actuators →
RunRecord (persisted on the plane) — for four policies. Only the model call and the
search tool are faked (no API key, no network to a real LLM); the server, control
plane, governor, ledger, and agent loop are all real.
"""

from __future__ import annotations

import dataclasses

import httpx
import pytest

pytestmark = pytest.mark.e2e

pytest.importorskip("fastapi")
from examples.agents.research.tools import core as search_core
from examples.agents.research.tools.core import SearchResult
from fastapi.testclient import TestClient

from tokenops.control.http_store import HttpStore
from tokenops.control.models import BudgetSpec, PolicyInstance
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


def _seed(plane_url: str, *, policies=(), budgets=()) -> None:
    """Configure the plane exactly the way a real deployment would — over its own
    HTTP API, not by touching whatever storage happens to sit behind it."""
    for b in budgets:
        httpx.put(
            f"{plane_url}/v1/budgets", json=dataclasses.asdict(b), timeout=10
        ).raise_for_status()
    for pi in policies:
        httpx.put(
            f"{plane_url}/v1/policies", json=dataclasses.asdict(pi), timeout=10
        ).raise_for_status()


def _client(live_plane_url, monkeypatch, policies, budgets=(), model=None):
    _seed(live_plane_url, policies=policies, budgets=budgets)
    monkeypatch.setattr(search_core, "search", _search)
    from examples.agents.research.native import server as srv

    if model is not None:
        monkeypatch.setattr(srv, "complete", model)

    async def _fake_delegate(*a, **k):  # summarize server isn't running in-test
        from examples.agents.types import TokenUsage

        return ("summary", TokenUsage(), [], 0)

    monkeypatch.setattr(srv, "delegate_summarize", _fake_delegate)
    return srv, TestClient(srv.build_app())


def _always_search(provider, model, messages, max_output_tokens=None, **kw):
    return ModelResponse(
        content='{"action": "search", "query": "pricing"}', input_tokens=820, output_tokens=45
    )


# 1) step_cap, pulled from the control plane's own /v1/policies → HALT
def test_step_cap_halts(live_plane_url, monkeypatch):
    srv, client = _client(
        live_plane_url,
        monkeypatch,
        [PolicyInstance(id="p", template="step_cap", params={"max_steps": 2}, agent="research")],
        model=_always_search,
    )
    body = _run(client)
    assert body["status"] == "halted" and "step" in body["halt_reason"].lower()
    assert body["cost_micros"] > 0


# 2) cost_budget, budget + policy both configured on the plane → HALT
def test_cost_budget_halts(live_plane_url, monkeypatch):
    srv, client = _client(
        live_plane_url,
        monkeypatch,
        [PolicyInstance(id="p", template="cost_budget", budget_id="cap", agent="research")],
        budgets=[
            BudgetSpec(id="cap", limit_micros=250, dimension="run")
        ],  # ~150 micros/call → halts on 2nd
        model=_always_search,
    )
    body = _run(client)
    assert body["status"] == "halted" and "budget" in body["halt_reason"].lower()


# 3) output_runaway via streaming → CANCEL + RETRY → run completes
def test_cancel_retry_streaming(live_plane_url, monkeypatch):
    monkeypatch.setenv("TOKENOPS_STREAM", "1")
    calls = {"n": 0}

    def fake_stream(
        provider,
        model,
        messages,
        *,
        max_output_tokens=None,
        frequency_penalty=None,
        presence_penalty=None,
    ):
        i = calls["n"]
        calls["n"] += 1
        if i < 2:  # degenerate — gets cancelled mid-stream
            for _ in range(100):
                yield "loop "
        else:  # clean decision ends the agent loop
            yield '{"action": "finish"}'

    srv, client = _client(
        live_plane_url,
        monkeypatch,
        [
            PolicyInstance(
                id="p",
                template="output_runaway",
                params={"repeats": 4, "max_retries": 2},
                agent="research",
            )
        ],
    )
    monkeypatch.setattr(srv, "stream_complete", fake_stream)
    body = _run(client)
    assert body["status"] == "completed"  # CANCEL + RETRY recovered, no crash
    assert calls["n"] == 3  # 2 cancelled streams + 1 clean retry
    assert body["cost_micros"] > 0


# 4) tool_output_cap deep swap → the oversized result is replaced by the descriptor
def test_tool_output_cap_substitutes_result(live_plane_url, monkeypatch):
    big = "x" * 60_000

    def search_then_finish(provider, model, messages, max_output_tokens=None, **kw):
        # search on the first call, finish on the second
        n = search_then_finish.n = getattr(search_then_finish, "n", 0) + 1
        action = "search" if n == 1 else "finish"
        return ModelResponse(
            content=f'{{"action": "{action}", "query": "pricing"}}',
            input_tokens=100,
            output_tokens=10,
        )

    srv, client = _client(
        live_plane_url,
        monkeypatch,
        [
            PolicyInstance(
                id="p", template="tool_output_cap", params={"cap_tokens": 1000}, agent="research"
            )
        ],
        model=search_then_finish,
    )
    # patch the search AFTER _client (which sets a small default) so the result is oversized
    monkeypatch.setattr(
        search_core,
        "search",
        lambda q, profile="healthy": SearchResult(
            query=q, snippet=big, completeness=0.2, source="test"
        ),
    )
    body = _run(client)
    assert body["status"] == "completed"
    snippets = [f["snippet"] for f in body["findings"]]
    assert any(
        s.startswith("TOOL OUTPUT OFFLOADED") for s in snippets
    )  # deep swap landed in context


# 5) only allow-listed payload dims reach the persisted RunRecord (segmentation
#    backbone, and the attribution-hardening boundary — an untrusted request body
#    must not be able to inject arbitrary segmentation tags; see
#    attribution._PAYLOAD_USER_DIM_ALLOWLIST, commit 28337d1 "Harden ...").
def test_run_dims_only_allowlisted_payload_keys_persist(live_plane_url, monkeypatch):
    srv, client = _client(
        live_plane_url,
        monkeypatch,
        [PolicyInstance(id="p", template="step_cap", params={"max_steps": 2}, agent="research")],
        model=_always_search,
    )
    body = _run(client, user_dims={"user_id": "alice", "team": "growth"})
    run_id = body["run_id"]
    hs = HttpStore(live_plane_url)
    rec = hs.get_run(run_id)
    assert rec.dims.get("user_id") == "alice"  # allow-listed payload key persists
    assert "team" not in rec.dims  # arbitrary payload tag must not leak into segmentation
    hs.close()
