"""E2E: registration → attribution → ledger → policy enforcement (in-process)."""

from __future__ import annotations

import pytest

from tokenops.control import ApplyControls, Halt, build_governor, wrap_complete
from tokenops.control.attribution import _build_attribution
from tokenops.control.context import SpanContext, _governance_scope, run_scope
from tokenops.control.ledger import LIFETIME, RUN_TOTAL_BUDGET, segment_key_for
from tokenops.control.models import PolicyInstance, RunRegistration
from tokenops.control.pricing import build_price_book
from tokenops.control.store import Store


def _fake_complete(provider, model, messages, max_output_tokens=None, **kwargs):
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
    """Register → govern complete loop → assert attribution on ledger, spend, and HALT."""
    reg = store.register_run(
        RunRegistration(
            run_id="e2e-run-1",
            intent="f500_frontier",
            user_dims={"Country": "US", "IsFortune500": "true", "user_id": "alice"},
        )
    )
    attr = _build_attribution(reg, service="research")

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
        gov,
        gov.controls,
        attr,
        provider="openai",
        model="gpt-4o-mini",
        dispatch=_fake_complete,
        service="research",
    )

    with run_scope(reg, SpanContext(span_id="span-root", service="research")):
        with _governance_scope(gov, attr, provider="openai", model="gpt-4o-mini"):
            with pytest.raises(Halt) as exc:
                for _ in range(20):
                    governed(
                        "openai", "gpt-4o-mini", [{"role": "user", "content": "Research pricing"}]
                    )

    assert "step" in exc.value.action.reason.lower()
    assert gov.ledger.is_halted("e2e-run-1")

    assert gov.ledger.step_count("e2e-run-1") >= 3
    cost = gov.ledger.cost_micros("e2e-run-1")
    assert cost > 0

    run_key = "run:e2e-run-1"
    assert gov.ledger._spent[(RUN_TOTAL_BUDGET.budget_id, run_key, LIFETIME)] == cost

    window = gov.ledger.window("e2e-run-1")
    assert len(window) >= 3
    llm_steps = [s for s in window if s.node_type == "llm"]
    assert llm_steps
    assert llm_steps[0].tags.get("provider") == "openai"
    assert llm_steps[0].tags.get("model") == "gpt-4o-mini"
    assert llm_steps[-1].cum_spent_micros == cost
