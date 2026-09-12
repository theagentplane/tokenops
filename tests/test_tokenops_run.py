"""Tests for tokenops_run, RequestContext, init / crossing hook (Wave 1–2 API)."""

from __future__ import annotations

import chronicle.session as chronicle_session
import pytest
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
from tokenops.control.context import (
    RUN_ID_HEADER,
    clear,
    current_governance,
    current_registration,
)
from tokenops.control.crossing import install_crossing_hook, on_crossing
from tokenops.control.governance_cache import clear_governance_config_cache
from tokenops.control.models import GovernanceMode
from tokenops.control.store import Store


@pytest.fixture
def store(tmp_path):
    """Explicit test-injection Store — tokenops_run(store=store) / ControlPlaneClient
    (store=store) — never reachable from ControlPlaneClient.from_env() (tokenops#118)."""
    db = str(tmp_path / "wave1.db")
    clear_governance_config_cache()
    s = Store(db)
    yield s
    clear()
    clear_request_context()
    clear_governance_config_cache()
    s.close()


def test_init_installs_crossing_hook():
    init()
    assert getattr(chronicle_session.reset_session, "_tokenops_crossing_hook", False)
    session = chronicle_session.reset_session()
    assert session.on_crossing is on_crossing


def test_from_env_installs_crossing_hook(live_plane_url):
    # Force a fresh look: hook is already installed in-process; still must not raise.
    client = ControlPlaneClient.from_env()
    assert not client.embedded
    assert client.url == live_plane_url
    assert getattr(chronicle_session.reset_session, "_tokenops_crossing_hook", False)
    install_crossing_hook()  # idempotent


def test_from_env_raises_without_a_url(monkeypatch):
    """tokenops#118: no embedded fallback — from_env() must fail closed."""
    monkeypatch.delenv("CONTROL_PLANE_URL", raising=False)
    monkeypatch.delenv("TOKENOPS_URL", raising=False)
    monkeypatch.delenv("TOKENOPS_CONTROL_PLANE_URL", raising=False)
    with pytest.raises(RuntimeError, match="CONTROL_PLANE_URL"):
        ControlPlaneClient.from_env()


def test_tokenops_run_registers_when_no_run_id(store):
    clear()
    with tokenops_run(
        store=store,
        headers={},
        payload={"task": "do stuff"},
        service="planner",
        intent="triad_plan",
        mode="preview",
        user_dims={"tenant": "acme"},
    ) as bound:
        assert bound.registration.intent == "triad_plan"
        assert bound.registration.mode is GovernanceMode.PREVIEW
        assert bound.registration.user_dims["tenant"] == "acme"
        assert bound.attr.agent == "planner"
        assert bound.client is not None
        assert current_registration() is bound.registration
        assert current_governance() is not None
        assert current_governance().attr.run_id == bound.registration.run_id
        assert bound.governor.controls is bound.controls
    assert current_registration() is None
    assert current_governance() is None


def test_tokenops_run_without_user_passed_store(live_plane_url):
    """§6 happy path: from_env's real remote client — no store= from the caller."""
    clear()
    with tokenops_run(
        headers={},
        payload={"task": "no store kwarg"},
        service="planner",
        intent="triad_plan",
        mode="preview",
    ) as bound:
        assert bound.registration.intent == "triad_plan"
        assert not bound.client.embedded
        assert bound.client.url == live_plane_url
        assert bound.store is bound.client.require_store()
        assert bound.governor.ledger._backend is bound.client.backend
        assert current_governance() is not None
    clear()


def test_tokenops_run_joins_when_run_id_present(store):
    clear()
    client = ControlPlaneClient(store=store)
    out = client.register_run(intent="shared", mode="enforce", run_id="join-me")
    assert out["run_id"] == "join-me"

    with tokenops_run(
        client=client,
        headers={RUN_ID_HEADER: "join-me"},
        payload={"task": "hop"},
        service="researcher",
    ) as bound:
        assert bound.registration.run_id == "join-me"
        assert bound.registration.intent == "shared"
        assert bound.span.service == "researcher"
        assert current_governance() is not None
        assert client.resolve_run("join-me").intent == "shared"
    clear()


def test_agent_intent_beats_empty_and_payload_intent(store):
    """§1: agent kwargs win; payload intent is ignored on tokenops_run path."""
    clear()
    with tokenops_run(
        store=store,
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
        assert bound.registration.intent == "agent_owned"
        assert bound.registration.mode is GovernanceMode.ENFORCE
        assert bound.registration.user_dims["tenant"] == "t1"
        assert bound.registration.user_dims["user_id"] == "alice"
        assert "spoof_intent_tag" not in bound.registration.user_dims
    clear()


def test_request_context_ambient(live_plane_url):
    clear()
    clear_request_context()
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
    try:
        with tokenops_run() as bound:
            assert bound.registration.intent == "from_instrument"
            assert bound.registration.mode is GovernanceMode.PREVIEW
            assert bound.registration.user_dims["user_id"] == "bob"
            assert current_governance().provider == "openai"
            assert current_governance().model == "gpt-4o-mini"
    finally:
        clear_request_context()
        clear()


def test_instrument_app_binds_context_and_hook(live_plane_url):
    app = FastAPI()
    instrument_app(app, service="planner", intent="mw_intent", mode="enforce")

    @app.post("/v1/tasks")
    async def tasks():
        with tokenops_run() as bound:
            return {
                "run_id": bound.registration.run_id,
                "intent": bound.registration.intent,
                "service": bound.span.service,
            }

    client = TestClient(app)
    res = client.post("/v1/tasks", json={"task": "hello", "intent": "ui_should_lose"})
    assert res.status_code == 200
    body = res.json()
    assert body["intent"] == "mw_intent"
    assert body["service"] == "planner"
    assert body["run_id"]
    assert getattr(chronicle_session.reset_session, "_tokenops_crossing_hook", False)
