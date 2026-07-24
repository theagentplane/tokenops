"""Budget HALT on a governed complete loop (no agent bench)."""

from __future__ import annotations

import pytest

from conftest import make_attr, toy_price
from tokenops.control import ApplyControls, Halt, build_governor, wrap_complete
from tokenops.control.context import SpanContext, _governance_scope, run_scope
from tokenops.control.models import RunRegistration


def test_budget_halts_governed_complete():
    from tokenops.providers.types import ModelResponse

    def fake_complete(provider, model, messages, max_output_tokens=None, **kwargs):
        return ModelResponse(
            content='{"action": "search", "query": "pricing"}',
            input_tokens=820,
            output_tokens=45,
        )

    config = {
        "governance": {
            "budgets": [{"id": "run_llm_cap", "limit_micros": 20_000, "dimension": "run"}],
            "policies": {"cost_budget": {"budget": "run_llm_cap"}},
        }
    }
    gov = build_governor(config, toy_price, ApplyControls())
    attr = make_attr(run_id="live-1")
    gov.ledger.open_run("live-1")
    reg = RunRegistration(run_id="live-1", intent="demo", user_dims={"user_id": "alice"})

    governed = wrap_complete(
        gov,
        gov.controls,
        attr,
        provider="openai",
        model="gpt-4o-mini",
        dispatch=fake_complete,
    )

    with run_scope(reg, SpanContext(span_id="s1", service="research")):
        with _governance_scope(gov, attr, provider="openai", model="gpt-4o-mini"):
            with pytest.raises(Halt):
                for _ in range(20):
                    governed(
                        "openai", "gpt-4o-mini", [{"role": "user", "content": "Research pricing"}]
                    )

    assert gov.ledger.is_halted("live-1")
    # 9550 micros/model-call → halts once cumulative ≥ 20_000 (i.e. on the 3rd call)
    assert gov.ledger.cost_micros("live-1") == 9550 * 3
    assert gov.ledger.step_count("live-1") >= 3
