"""The research to summarize example end to end against a real control plane.

Two real A2A servers in this process call each other over HTTP and share one budget through
one Chronicle trace. The model is scripted and the search is the offline corpus.
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

# 100_000 input tokens on gpt-4o-mini is 15_000 micros. Research uses two calls (search, then
# finish) and the summarizer one: 45_000 crosses the 40_000 cap on the summarizer's call.
CALL_TOKENS = 100_000
CAP_MICROS = 40_000


def _scripted_model(provider, model, messages, max_output_tokens=None, **kwargs):
    system = str(messages[0]["content"])
    user = str(messages[1]["content"]) if len(messages) > 1 else ""
    if "research agent" in system:
        action = "finish" if "step 2" in user.lower() or "Findings so far" in user else "search"
        content = json.dumps({"action": action, "query": "tokenops budgets"})
    else:
        content = "A short summary."
    return ModelResponse(content=content, input_tokens=CALL_TOKENS, output_tokens=0)


@pytest.fixture
def pair(monkeypatch):
    from examples.agents.research.native import server as research_server
    from examples.agents.summarize.native import server as summarize_server
    from examples.app_config import load_config

    from local_plane import API_KEY, LocalPlane

    with LocalPlane() as plane:
        plane.configure_cost_cap(CAP_MICROS)
        monkeypatch.setenv("CONTROL_PLANE_URL", plane.url)
        monkeypatch.setenv("CONTROL_PLANE_API_KEY", API_KEY)
        monkeypatch.setenv("SEARCH_BACKEND", "corpus")

        research_port, summarize_port = free_port(), free_port()
        research_url = f"http://127.0.0.1:{research_port}"
        summarize_url = f"http://127.0.0.1:{summarize_port}"
        base = load_config()
        cfg = replace(
            base,
            research=replace(
                base.research,
                url=research_url,
                port=research_port,
                summarize_url=summarize_url,
                framework="native",
                max_steps=6,
            ),
            summarize=replace(
                base.summarize, url=summarize_url, port=summarize_port, framework="native"
            ),
        )
        for module in (research_server, summarize_server):
            monkeypatch.setattr(module, "load_config", lambda cfg=cfg: cfg)
            monkeypatch.setattr(module, "complete", _scripted_model)

        # Built last so the research server's Chronicle settings (peer allow-listed) are the
        # live ones in this single process; in a deployment each server is its own process.
        summarize_app = summarize_server.build_app()
        research_app = research_server.build_app()
        with ServerThread(summarize_app, summarize_port), ServerThread(research_app, research_port):
            yield plane, research_url


def test_research_and_summarize_share_one_budget_and_one_trace(pair):
    plane, research_url = pair

    response = httpx.post(
        f"{research_url}/v1/tasks", json={"task": "Explain TokenOps budgets."}, timeout=60
    )
    response.raise_for_status()
    trace_id = response.json()["trace_id"]

    assert flush_ledger_writes(10)
    chronicle.flush()
    trace = plane.wait_for_trace(trace_id)

    # The summarizer's call crossed the cap that research had already spent most of.
    assert trace["attributes"]["tokenops.halted"] is True
    assert "run_llm_cap" in trace["attributes"]["tokenops.halt_reason"]

    deadline = time.monotonic() + 10
    spans: list[dict] = []
    while time.monotonic() < deadline:
        chronicle.flush()
        spans = plane.trace(trace_id).get("spans", [])
        if len(spans) >= 2:
            break
        time.sleep(0.1)
    assert len(spans) >= 2, spans
