"""Preview governance mode — detect and decide without pushing enforcement."""

from __future__ import annotations

import pytest

from tokenops.control import (
    ActionKind,
    Halt,
    PreviewControls,
    build_governance_stack,
    wrap_complete,
)
from tokenops.control.context import SpanContext, governance_scope, run_scope
from tokenops.control.models import GovernanceMode, PolicyInstance, RunRegistration
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
    s = Store(str(tmp_path / "preview.db"))
    s.upsert_policy_instance(
        PolicyInstance(
            id="pi_step",
            template="step_cap",
            params={"max_steps": 2},
            agent="research",
        )
    )
    yield s
    s.close()


def test_preview_mode_records_actions_without_halting(store):
    reg = store.register_run(
        RunRegistration(run_id="preview-run", intent="demo", mode=GovernanceMode.PREVIEW),
    )
    cfg = store.governance_config_for("research")
    gov, controls = build_governance_stack(
        cfg, build_price_book(), store=store, mode=GovernanceMode.PREVIEW,
    )
    assert isinstance(controls, PreviewControls)
    gov.ledger.open_run("preview-run")

    from tokenops.control import build_attribution

    attr = build_attribution(reg, service="research")
    governed = wrap_complete(
        gov, controls, attr,
        provider="openai", model="gpt-4o-mini",
        dispatch=_fake_complete, service="research",
    )

    with run_scope(reg, SpanContext(span_id="s1", service="research")):
        with governance_scope(gov, attr, provider="openai", model="gpt-4o-mini"):
            for _ in range(5):
                governed("openai", "gpt-4o-mini", [{"role": "user", "content": "task"}])

    assert not gov.ledger.is_halted("preview-run")
    assert any(a.kind is ActionKind.HALT for a in controls.actions)
    assert controls.preview_summary()


def test_enforce_mode_still_halts(store):
    reg = store.register_run(RunRegistration(run_id="enforce-run", intent="demo"))
    cfg = store.governance_config_for("research")
    gov, controls = build_governance_stack(
        cfg, build_price_book(), store=store, mode=GovernanceMode.ENFORCE,
    )
    gov.ledger.open_run("enforce-run")

    from tokenops.control import build_attribution

    attr = build_attribution(reg, service="research")
    governed = wrap_complete(
        gov, controls, attr,
        provider="openai", model="gpt-4o-mini",
        dispatch=_fake_complete, service="research",
    )

    with run_scope(reg, SpanContext(span_id="s1", service="research")):
        with governance_scope(gov, attr, provider="openai", model="gpt-4o-mini"):
            with pytest.raises(Halt):
                for _ in range(10):
                    governed("openai", "gpt-4o-mini", [{"role": "user", "content": "task"}])

    assert gov.ledger.is_halted("enforce-run")


def test_registration_persists_mode(store):
    reg = store.register_run(
        RunRegistration(run_id="r-mode", intent="x", mode=GovernanceMode.PREVIEW),
    )
    loaded = store.resolve_run("r-mode")
    assert loaded.mode is GovernanceMode.PREVIEW


def test_parse_governance_mode_invalid():
    from tokenops.control.models import parse_governance_mode

    with pytest.raises(ValueError, match="unknown governance mode"):
        parse_governance_mode("bogus")
