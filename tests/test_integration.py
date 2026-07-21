"""Phase 5 — the IN tap halts a REAL NativeResearchAgent run, offline.

The only thing faked is the model HTTP call (no API key needed); the agent loop, the corpus
search tool, and the whole control plane are real.
"""

from __future__ import annotations

import pytest

from tokenops.control import Halt, build_governor
from tokenops.control.integration import make_on_step
from conftest import make_attr, toy_price


def test_budget_halts_live_native_agent(monkeypatch):
    from bench.agents.research.native import agent as agent_mod
    from tokenops.config.schema import AgentServerConfig
    from tokenops.providers.types import ModelResponse

    # fake the model call: always decide "search", report a fixed token usage (9550 micros each)
    def fake_complete(provider, model, messages):
        return ModelResponse(content='{"action": "search", "query": "pricing"}',
                             input_tokens=820, output_tokens=45)

    monkeypatch.setattr(agent_mod, "complete", fake_complete)

    config = {
        "governance": {
            "budgets": [{"id": "run_llm_cap", "limit_micros": 20_000, "dimension": "run"}],
            "policies": {"cost_budget": {"budget": "run_llm_cap"}},
        }
    }
    gov = build_governor(config, toy_price)
    attr = make_attr(run_id="live-1")
    gov.ledger.open_run("live-1")

    on_step = make_on_step(gov, attr, provider="openai", model="gpt-4o-mini")
    # satisfaction_threshold > 1 so the loop never "finishes"; max_steps high so the breaker stops it
    agent = agent_mod.NativeResearchAgent(AgentServerConfig(max_steps=50, satisfaction_threshold=2.0))

    with pytest.raises(Halt):
        agent.run("Research pricing", "healthy", on_step=on_step)

    assert gov.ledger.is_halted("live-1")
    # 9550 micros/model-call → halts once cumulative ≥ 20_000 (i.e. on the 3rd call)
    assert gov.ledger.cost_micros("live-1") == 9550 * 3
    assert gov.ledger.step_count("live-1") >= 3
