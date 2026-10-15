"""E2E: registration → attribution → ledger → policy enforcement (in-process)."""

from __future__ import annotations

import pytest

from tokenops.capabilities import wrap_complete
from tokenops.framework.attribution import _build_attribution
from tokenops.framework.config import build_governor
from tokenops.framework.context import SpanContext, _governance_scope, run_scope
from tokenops.framework.core import Halt
from tokenops.framework.engine import ApplyControls
from tokenops.framework.ledger import LIFETIME, TRACE_TOTAL_BUDGET, segment_key_for
from tokenops.framework.models import HopAttribution
from tokenops.framework.pricing import build_price_book


def _fake_complete(provider, model, messages, max_output_tokens=None, **kwargs):
    from tokenops.providers.types import ModelResponse

    return ModelResponse(
        content='{"action": "search", "query": "pricing"}',
        input_tokens=820,
        output_tokens=45,
    )


CONFIG = {"governance": {"budgets": [], "policies": {"step_cap": {"max_steps": 3}}}}


def test_attribution_ledger_and_policy_e2e_in_process():
    """Attribute → govern complete loop → assert attribution on ledger, spend, and HALT."""
    reg = HopAttribution(
        trace_id="e2e-run-1",
        intent="f500_frontier",
        user_dims={"Country": "US", "IsFortune500": "true", "user_id": "alice"},
    )
    attr = _build_attribution(reg, service="research")

    assert attr.trace_id == "e2e-run-1"
    assert attr.agent == "research"
    assert attr.user == "alice"
    assert attr.tags["intent"] == "f500_frontier"
    assert attr.tags["Country"] == "US"
    assert segment_key_for(attr, "tag", "intent") == "tag:intent=f500_frontier"
    assert segment_key_for(attr, "tag", "Country") == "tag:Country=US"
    assert segment_key_for(attr, "trace") == "trace:e2e-run-1"
    assert segment_key_for(attr, "agent") == "agent:research"

    gov = build_governor(CONFIG, build_price_book(), ApplyControls())
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

    run_key = "trace:e2e-run-1"
    assert gov.ledger._spent[(TRACE_TOTAL_BUDGET.budget_id, run_key, LIFETIME)] == cost

    window = gov.ledger.window("e2e-run-1")
    assert len(window) >= 3
    llm_steps = [s for s in window if s.node_type == "llm"]
    assert llm_steps
    assert llm_steps[0].tags.get("provider") == "openai"
    assert llm_steps[0].tags.get("model") == "gpt-4o-mini"
    assert llm_steps[-1].cum_spent_micros == cost
