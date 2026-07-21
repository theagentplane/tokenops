"""Store-defined policy enforces on a live governed complete loop (no agent bench)."""

from __future__ import annotations

import pytest

from tokenops.control import (
    ApplyControls,
    Halt,
    build_attribution,
    build_governor,
    wrap_complete,
)
from tokenops.control.context import SpanContext, governance_scope, run_scope
from tokenops.control.models import PolicyInstance, RunRegistration
from tokenops.control.pricing import build_price_book
from tokenops.control.store import Store


def _fake_complete(provider, model, messages, max_output_tokens=None, **kwargs):
    from tokenops.providers.types import ModelResponse
    return ModelResponse(content='{"action": "search", "query": "x"}', input_tokens=10, output_tokens=2)


def test_store_policy_halts_governed_complete(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    s.upsert_policy_instance(PolicyInstance(
        id="pi", template="step_cap", params={"max_steps": 2}, agent="research",
    ))
    reg = s.register_run(RunRegistration(run_id="run-1", intent="demo"))
    cfg = s.governance_config_for("research")

    gov = build_governor(cfg, build_price_book(), ApplyControls())
    attr = build_attribution(reg, service="research")
    gov.ledger.open_run("run-1")

    governed = wrap_complete(
        gov, gov.controls, attr,
        provider="openai", model="gpt-4o-mini",
        dispatch=_fake_complete,
    )

    with run_scope(reg, SpanContext(span_id="s1", service="research")):
        with governance_scope(gov, attr, provider="openai", model="gpt-4o-mini"):
            with pytest.raises(Halt):
                for _ in range(20):
                    governed("openai", "gpt-4o-mini", [{"role": "user", "content": "continue"}])

    assert gov.ledger.is_halted("run-1")
    assert gov.ledger.step_count("run-1") >= 2
    s.close()
