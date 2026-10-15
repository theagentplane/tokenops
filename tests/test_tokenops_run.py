"""Tests for tokenops_run, RequestContext, init / crossing hook."""

from __future__ import annotations

import logging

import pytest
from chronicle import default_hooks
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tokenops import (
    ControlPlaneClient,
    RequestContext,
    bind_request_context,
    clear_request_context,
    init,
    instrument_app,
    tokenops_run,
)
from tokenops.capabilities.crossing import TokenOpsHook, install_crossing_hook
from tokenops.framework.context import (
    clear,
    current_governance,
    current_hop,
)
from tokenops.framework.models import GovernanceMode
from tokenops.repositories import ControlPlaneError, ControlPlaneUnavailable

CONFIG = {
    "governance": {
        "budgets": [{"id": "run_llm_cap", "limit_micros": 1_000_000, "dimension": "trace"}],
        "policies": {"step_cap": {"max_steps": 5}},
    }
}


@pytest.fixture(autouse=True)
def _clean():
    clear()
    clear_request_context()
    yield
    clear()
    clear_request_context()


def test_init_installs_crossing_hook():
    init()
    install_crossing_hook()  # idempotent
    assert sum(isinstance(h, TokenOpsHook) for h in default_hooks) == 1


def test_from_env_requires_a_url(monkeypatch):
    monkeypatch.delenv("CONTROL_PLANE_URL", raising=False)
    with pytest.raises(ControlPlaneError, match="CONTROL_PLANE_URL"):
        ControlPlaneClient.from_env()


def test_run_with_an_explicit_config_needs_no_control_plane(monkeypatch):
    monkeypatch.delenv("CONTROL_PLANE_URL", raising=False)
    with tokenops_run(
        config=CONFIG,
        payload={"task": "do stuff"},
        service="planner",
        intent="triad_plan",
        mode="preview",
        user_dims={"tenant": "acme"},
    ) as bound:
        assert bound.hop.intent == "triad_plan"
        assert bound.hop.mode is GovernanceMode.PREVIEW
        assert bound.hop.user_dims["tenant"] == "acme"
        assert bound.attr.agent == "planner"
        assert bound.client is None
        assert current_hop() is bound.hop
        assert current_governance() is not None
        assert current_governance().attr.trace_id == bound.hop.trace_id
        assert bound.governor.controls is bound.controls
    assert current_hop() is None
    assert current_governance() is None


def test_the_run_is_the_chronicle_trace(monkeypatch):
    monkeypatch.delenv("CONTROL_PLANE_URL", raising=False)
    trace = "a" * 32
    with tokenops_run(
        config=CONFIG,
        headers={"traceparent": f"00-{trace}-{'b' * 16}-01"},
        payload={"task": "hop"},
        service="researcher",
    ) as bound:
        assert bound.hop.trace_id == trace
        assert bound.attr.trace_id == trace
        assert bound.span.service == "researcher"


def test_a_new_trace_is_started_without_an_inbound_traceparent():
    with tokenops_run(config=CONFIG, service="planner") as bound:
        assert len(bound.hop.trace_id) == 32


def test_governance_is_pulled_from_the_plane_and_the_ledger_uses_it(fake_plane):
    fake_plane.set_governance("planner", CONFIG)
    client = fake_plane.client()
    with tokenops_run(client=client, service="planner", payload={}) as bound:
        assert bound.client is client
        assert bound.governor.ledger._backend is client
        assert "step_cap" in bound.governor._policy_by_name
    assert any(r.url.path == "/v1/governance/planner" for r in fake_plane.requests)


def test_a_stale_configuration_is_used_when_the_plane_goes_down(fake_plane, caplog):
    fake_plane.set_governance("planner", CONFIG)
    client = fake_plane.client()
    with tokenops_run(client=client, service="planner"):
        pass
    fake_plane.down = True
    with caplog.at_level(logging.WARNING, logger="tokenops.run"):
        with tokenops_run(client=client, service="planner", open_ledger_run=False) as bound:
            assert "step_cap" in bound.governor._policy_by_name
    assert any("governance_stale" in r.message for r in caplog.records)


def test_the_hop_does_not_run_when_the_plane_is_down_and_nothing_is_cached(fake_plane):
    """Fail closed: no configuration means no governed run, never an ungoverned one."""
    fake_plane.down = True
    with pytest.raises(ControlPlaneUnavailable):
        with tokenops_run(client=fake_plane.client(), service="planner"):
            pytest.fail("the body must not run")


def test_no_plane_and_no_config_fails_closed(monkeypatch):
    monkeypatch.delenv("CONTROL_PLANE_URL", raising=False)
    with pytest.raises(ControlPlaneError, match="CONTROL_PLANE_URL"):
        with tokenops_run(service="planner"):
            pytest.fail("the body must not run")


def test_agent_intent_beats_empty_and_payload_intent():
    """Agent kwargs win; payload intent is ignored on the tokenops_run path."""
    with tokenops_run(
        config=CONFIG,
        headers={},
        payload={
            "task": "only work",
            "intent": "from_ui",
            "mode": "preview",
            "user_dims": {"user_id": "alice", "spoof_intent_tag": "nope"},
        },
        service="planner",
        intent="agent_owned",
        mode="enforce",
        user_dims={"tenant": "t1"},
    ) as bound:
        assert bound.hop.intent == "agent_owned"
        assert bound.hop.mode is GovernanceMode.ENFORCE
        assert bound.hop.user_dims["tenant"] == "t1"
        assert bound.hop.user_dims["user_id"] == "alice"
        assert "spoof_intent_tag" not in bound.hop.user_dims


def test_request_context_ambient():
    bind_request_context(
        RequestContext(
            headers={},
            payload={"task": "ambient", "user_dims": {"user_id": "bob"}},
            service="planner",
            intent="from_instrument",
            mode="preview",
            provider="openai",
            model="gpt-4o-mini",
        )
    )
    with tokenops_run(config=CONFIG) as bound:
        assert bound.hop.intent == "from_instrument"
        assert bound.hop.mode is GovernanceMode.PREVIEW
        assert bound.hop.user_dims["user_id"] == "bob"
        assert current_governance().provider == "openai"
        assert current_governance().model == "gpt-4o-mini"


def test_instrument_app_binds_context_and_hook():
    app = FastAPI()
    instrument_app(app, service="planner", intent="mw_intent", mode="enforce")

    @app.post("/v1/tasks")
    async def tasks():
        with tokenops_run(config=CONFIG) as bound:
            return {
                "trace_id": bound.hop.trace_id,
                "intent": bound.hop.intent,
                "service": bound.span.service,
            }

    client = TestClient(app)
    res = client.post("/v1/tasks", json={"task": "hello", "intent": "ui_should_lose"})
    assert res.status_code == 200
    body = res.json()
    assert body["intent"] == "mw_intent"
    assert body["service"] == "planner"
    assert body["trace_id"]
