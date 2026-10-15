"""The LangChain brief example (scout, analyst, editor) end to end against a real control plane.

The agents use LangChain chat models bridged to TokenOps (``GovernedChatModel``); the model call
underneath is scripted and the search is the offline corpus. Skipped without LangChain.
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

pytest.importorskip("langchain_core")

try:
    _PLANE_MAJOR = int(version("agentplane-control-plane").split(".")[0])
except PackageNotFoundError:  # pragma: no cover - environment dependent
    _PLANE_MAJOR = 0

pytestmark = pytest.mark.skipif(
    _PLANE_MAJOR < 1, reason="needs agentplane-control-plane>=1.0 installed"
)

CALL_TOKENS = 100_000
CAP_MICROS = 40_000  # three calls at 15_000 micros each cross it


def _scripted_model(provider, model, messages, max_output_tokens=None, **kwargs):
    system = str(messages[0]["content"])
    if "scouting agent" in system:
        content = json.dumps({"angles": ["cost"], "sections": ["Intro"]})
    elif "analyst agent" in system:
        content = json.dumps({"action": "finish"})
    else:
        content = "A short brief."
    return ModelResponse(content=content, input_tokens=CALL_TOKENS, output_tokens=0)


@pytest.fixture
def brief(monkeypatch):
    from examples.app_config import load_config
    from examples.brief.analyst import server as analyst_server
    from examples.brief.editor import server as editor_server
    from examples.brief.scout import server as scout_server

    from local_plane import API_KEY, LocalPlane

    with LocalPlane() as plane:
        plane.configure_cost_cap(CAP_MICROS)
        monkeypatch.setenv("CONTROL_PLANE_URL", plane.url)
        monkeypatch.setenv("CONTROL_PLANE_API_KEY", API_KEY)
        monkeypatch.setenv("SEARCH_BACKEND", "corpus")
        # The agents build a LangChain chat model at construction; it is never called here
        # (the governed dispatch is scripted), but its client needs a key to be created.
        monkeypatch.setenv("OPENAI_API_KEY", "test-key-never-sent")

        ports = {name: free_port() for name in ("scout", "analyst", "editor")}
        urls = {name: f"http://127.0.0.1:{port}" for name, port in ports.items()}
        base = load_config()
        cfg = replace(
            base,
            scout=replace(
                base.scout,
                url=urls["scout"],
                port=ports["scout"],
                analyst_url=urls["analyst"],
                editor_url=urls["editor"],
            ),
            analyst=replace(base.analyst, url=urls["analyst"], port=ports["analyst"]),
            editor=replace(base.editor, url=urls["editor"], port=ports["editor"]),
        )
        for module in (scout_server, analyst_server, editor_server):
            monkeypatch.setattr(module, "load_config", lambda cfg=cfg: cfg)
            monkeypatch.setattr(module, "make_langchain_dispatch", lambda *a, **k: _scripted_model)

        analyst_app = analyst_server.build_app()
        editor_app = editor_server.build_app()
        scout_app = scout_server.build_app()
        with (
            ServerThread(analyst_app, ports["analyst"]),
            ServerThread(editor_app, ports["editor"]),
            ServerThread(scout_app, ports["scout"]),
        ):
            yield plane, urls


def test_the_brief_shares_one_budget_and_one_trace(brief):
    plane, urls = brief

    response = httpx.post(
        f"{urls['scout']}/v1/tasks", json={"task": "Brief on TokenOps budgets."}, timeout=60
    )
    response.raise_for_status()
    trace_id = response.json()["trace_id"]

    assert flush_ledger_writes(10)
    chronicle.flush()
    trace = plane.wait_for_trace(trace_id)

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
