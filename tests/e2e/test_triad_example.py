"""The triad example (planner, researcher, writer) end to end against a real control plane.

Three real A2A servers run in this process on free localhost ports, call each other over HTTP,
and share one budget through one Chronicle trace (``traceparent``). The model is scripted and
the search is the offline corpus; everything else is the example code.
"""

from __future__ import annotations

import json
import time
from dataclasses import replace
from importlib.metadata import PackageNotFoundError, version

import chronicle
import httpx
import pytest
from example_servers import ServerThread, free_port

from tokenops import flush_ledger_writes
from tokenops.providers.types import ModelResponse

try:
    _PLANE_MAJOR = int(version("agentplane-control-plane").split(".")[0])
except PackageNotFoundError:  # pragma: no cover - environment dependent
    _PLANE_MAJOR = 0

pytestmark = pytest.mark.skipif(
    _PLANE_MAJOR < 1, reason="needs agentplane-control-plane>=1.0 installed"
)

# 100_000 input tokens on gpt-4o-mini is 15_000 micros: the cap allows three model calls in all.
CALL_TOKENS = 100_000
CAP_MICROS = 50_000


def _scripted_model(provider, model, messages, max_output_tokens=None, **kwargs):
    system = str(messages[0]["content"])
    if "planning agent" in system:
        content = json.dumps({"questions": ["What is TokenOps?"], "outline": ["Intro", "Body"]})
    elif "research agent" in system:
        content = json.dumps({"action": "search", "query": "tokenops budgets"})
    else:
        content = "A short answer."
    return ModelResponse(content=content, input_tokens=CALL_TOKENS, output_tokens=0)


@pytest.fixture
def triad(monkeypatch):
    from examples.app_config import load_config
    from examples.triad.planner import server as planner_server
    from examples.triad.researcher import server as researcher_server
    from examples.triad.writer import server as writer_server

    from local_plane import API_KEY, LocalPlane

    with LocalPlane() as plane:
        plane.configure_cost_cap(CAP_MICROS)
        monkeypatch.setenv("CONTROL_PLANE_URL", plane.url)
        monkeypatch.setenv("CONTROL_PLANE_API_KEY", API_KEY)
        monkeypatch.setenv("SEARCH_BACKEND", "corpus")

        ports = {name: free_port() for name in ("planner", "researcher", "writer")}
        urls = {name: f"http://127.0.0.1:{port}" for name, port in ports.items()}
        base = load_config()
        cfg = replace(
            base,
            planner=replace(
                base.planner,
                url=urls["planner"],
                port=ports["planner"],
                researcher_url=urls["researcher"],
                writer_url=urls["writer"],
            ),
            researcher=replace(
                base.researcher, url=urls["researcher"], port=ports["researcher"], max_steps=10
            ),
            writer=replace(base.writer, url=urls["writer"], port=ports["writer"]),
        )
        for module in (planner_server, researcher_server, writer_server):
            monkeypatch.setattr(module, "load_config", lambda cfg=cfg: cfg)
            monkeypatch.setattr(module, "complete", _scripted_model)

        # Built last, so the planner's Chronicle settings (peers allow-listed) are the live ones
        # in this single process; in a deployment each server is its own process.
        researcher_app = researcher_server.build_app()
        writer_app = writer_server.build_app()
        planner_app = planner_server.build_app()
        with (
            ServerThread(researcher_app, ports["researcher"]),
            ServerThread(writer_app, ports["writer"]),
            ServerThread(planner_app, ports["planner"]),
        ):
            yield plane, urls


def test_the_triad_shares_one_budget_and_one_trace(triad):
    plane, urls = triad

    response = httpx.post(
        f"{urls['planner']}/v1/tasks", json={"task": "Explain TokenOps budgets."}, timeout=60
    )
    response.raise_for_status()
    body = response.json()

    # The budget is shared: the researcher's calls count against the planner's run.
    assert body["status"] == "halted"
    trace_id = body["trace_id"]

    assert flush_ledger_writes(10)
    chronicle.flush()
    trace = plane.wait_for_trace(trace_id)
    assert trace["attributes"]["tokenops.halted"] is True
    # The first agent to cross the shared cap marked the halt; the others were refused after it.
    assert "run_llm_cap" in trace["attributes"]["tokenops.halt_reason"]

    # One trace across the hops: the planner's span and the researcher's span, joined by
    # traceparent (distinct spans, the same trace id).
    deadline = time.monotonic() + 10
    spans: list[dict] = []
    while time.monotonic() < deadline:
        chronicle.flush()
        spans = plane.trace(trace_id).get("spans", [])
        if len(spans) >= 2:
            break
        time.sleep(0.1)
    assert len(spans) >= 2, spans
    assert len({s["span_id"] for s in spans}) == len(spans)
