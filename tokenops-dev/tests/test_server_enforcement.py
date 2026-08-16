"""S1+S3 (+S4/S7 over HTTP) — a store-defined policy enforces on a live governed agent.

The first test proves the core loop (store config -> build_governor -> governed agent -> HALT)
with no web stack. The second exercises the real FastAPI handler + persisted RunRecord, and
is skipped where fastapi isn't installed.
"""

from __future__ import annotations

import pytest

from tokenops.control import (
    Attribution,
    ApplyControls,
    Halt,
    build_governor,
    make_on_step,
    wrap_complete,
)
from tokenops.control.models import PolicyInstance
from tokenops.control.pricing import build_price_book
from tokenops.control.store import Store


def _fake_complete(provider, model, messages, max_output_tokens=None):
    from tokenops.providers.types import ModelResponse
    return ModelResponse(content='{"action": "search", "query": "x"}', input_tokens=10, output_tokens=2)


def test_store_policy_halts_governed_agent(tmp_path):
    from tokenops.agents.research.native.agent import NativeResearchAgent
    from tokenops.config.schema import AgentServerConfig

    s = Store(str(tmp_path / "t.db"))
    s.upsert_policy_instance(PolicyInstance(id="pi", template="step_cap",
                                            params={"max_steps": 2}, agent="research"))
    cfg = s.governance_config_for("research")

    gov = build_governor(cfg, build_price_book(), ApplyControls())
    attr = Attribution(user="u", agent="research", run_id="run-1")
    gov.ledger.open_run("run-1")
    steps = []
    record = make_on_step(gov, attr, provider="openai", model="gpt-4o-mini")

    def on_step(event):
        steps.append(event)
        record(event)

    governed = wrap_complete(gov, gov.controls, attr, provider="openai", model="gpt-4o-mini",
                             dispatch=_fake_complete)
    agent = NativeResearchAgent(AgentServerConfig(max_steps=20, satisfaction_threshold=2.0))

    with pytest.raises(Halt):
        agent.run("t", "healthy", on_step, governed)
    assert gov.ledger.is_halted("run-1")
    assert gov.ledger.step_count("run-1") >= 2
    s.close()


def test_research_server_http_boundary(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    db = str(tmp_path / "t.db")
    monkeypatch.setenv("TOKENOPS_DB", db)
    s = Store(db)
    s.upsert_policy_instance(PolicyInstance(id="pi", template="step_cap",
                                            params={"max_steps": 2}, agent="research"))
    s.close()

    from tokenops.agents.research.native import server as srv
    monkeypatch.setattr(srv, "complete", _fake_complete)

    resp = TestClient(srv.build_app()).post("/v1/tasks", json={"task": "t", "corpus_profile": "healthy"})
    body = resp.json()
    assert resp.status_code == 200 and body["status"] == "halted"
    assert "step" in body["halt_reason"].lower()

    s2 = Store(db)
    rec = s2.get_run(body["run_id"])
    s2.close()
    assert rec.status == "halted" and rec.steps >= 2
