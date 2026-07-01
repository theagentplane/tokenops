"""Control-plane API layer — RemoteStore round-trips and split-mode HTTP e2e."""

from __future__ import annotations

import socket
import threading
import time
from unittest.mock import patch

import httpx
import pytest
import uvicorn

from tokenops.control.models import PolicyInstance, RunRegistration
from tokenops.control.remote_store import RemoteStore
from tokenops.control.store import SqliteStore
from tokenops.control_plane.app import create_control_plane_app


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def cp_server(tmp_path):
    db = str(tmp_path / "split.db")
    backend = SqliteStore(db, auto_seed=False)
    backend.upsert_policy_instance(
        PolicyInstance(id="pi", template="step_cap", params={"max_steps": 2}, agent="research")
    )
    app = create_control_plane_app(backend)
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            if httpx.get(f"{base}/health", timeout=0.5).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.05)
    else:
        raise RuntimeError("control plane did not start")
    yield base, backend
    server.should_exit = True
    thread.join(timeout=5)
    backend.close()


@pytest.fixture
def split_stack(cp_server, monkeypatch):
    base, backend = cp_server
    monkeypatch.setenv("TOKENOPS_CONTROL_PLANE_URL", base)
    remote = RemoteStore(base)
    yield remote, backend
    remote.close()


def test_remote_store_registration_and_governance(split_stack):
    remote, backend = split_stack
    reg = remote.register_run(RunRegistration(run_id="r1", intent="demo", user_dims={"user_id": "alice"}))
    assert reg.run_id == "r1"
    assert backend.get_run_registration("r1").intent == "demo"
    cfg = remote.governance_config_for("research")
    assert "step_cap" in cfg["governance"]["policies"]


def test_remote_store_ledger_roundtrip(split_stack):
    remote, backend = split_stack
    assert remote.ledger_add_spent("run_llm_cap", "run:r1", "lifetime", 500) == 500
    assert remote.ledger_get_spent("run_llm_cap", "run:r1", "lifetime") == 500
    assert backend.ledger_get_spent("run_llm_cap", "run:r1", "lifetime") == 500
    remote.ledger_mark_halted("r1", "budget")
    assert remote.ledger_is_halted("r1")
    assert backend.ledger_is_halted("r1")


def test_split_mode_http_task_path(split_stack, monkeypatch):
    """Register on control plane; execute task on research agent via RemoteStore."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    remote, backend = split_stack

    def _fake_complete(provider, model, messages, max_output_tokens=None):
        from tokenops.providers.types import ModelResponse
        return ModelResponse(
            content='{"action": "search", "query": "pricing"}',
            input_tokens=820,
            output_tokens=45,
        )

    monkeypatch.setattr("tokenops.agents.research.native.server.open_store", lambda **_: remote)

    from tokenops.agents.research.native import server as srv

    async def _fake_delegate(*_a, **_k):
        from tokenops.agents.types import TokenUsage
        return "", TokenUsage(), [], 0

    with patch.object(srv, "complete", _fake_complete), patch.object(srv, "delegate_summarize", _fake_delegate):
        agent_client = TestClient(srv.build_app())
        reg = remote.register_run(RunRegistration(run_id="run-http", intent="demo", user_dims={"Country": "DE"}))
        run_id = reg.run_id

        task_resp = agent_client.post(
            "/v1/tasks",
            json={"task": "test task", "bench": {"corpus_profile": "healthy"}},
            headers={"X-TokenOps-Run-Id": run_id},
        )
        body = task_resp.json()
        assert task_resp.status_code == 200
        assert body["status"] == "halted"
        assert backend.get_run(run_id).status == "halted"
