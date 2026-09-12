"""HTTP tests for the standalone control-plane FastAPI app."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tokenops.control.client import should_mount_run_registration
from tokenops.control.http import mount_run_registration
from tokenops.control.store import Store
from tokenops.server.app import create_app


@pytest.fixture
def plane_client(tmp_path, monkeypatch):
    db = str(tmp_path / "plane.db")
    monkeypatch.setenv("TOKENOPS_DB", db)
    store = Store(db)
    app = create_app(store=store)
    with TestClient(app) as client:
        yield client, store, db
    store.close()


def test_health(plane_client):
    client, _, _ = plane_client
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_post_v1_runs(plane_client):
    client, store, _ = plane_client
    resp = client.post(
        "/v1/runs",
        json={
            "intent": "frontier",
            "user_dims": {"Country": "US", "user_id": "bob"},
            "mode": "enforce",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "registered"
    assert body["mode"] == "enforce"
    run_id = body["run_id"]

    reg = store.resolve_run(run_id)
    assert reg.intent == "frontier"
    assert reg.user_dims["Country"] == "US"


def test_post_v1_runs_conflict(plane_client):
    client, _, _ = plane_client
    payload = {"run_id": "r-dup", "intent": "a", "user_dims": {}}
    assert client.post("/v1/runs", json=payload).status_code == 201
    conflict = client.post("/v1/runs", json={**payload, "intent": "b"})
    assert conflict.status_code == 409


def test_should_mount_run_registration_is_always_false(monkeypatch):
    """tokenops#118: registration is always centralized on the plane now — there is
    no embedded mode left for an agent to self-host POST /v1/runs under, regardless
    of what's in the environment."""
    monkeypatch.delenv("TOKENOPS_URL", raising=False)
    assert should_mount_run_registration() is False

    monkeypatch.setenv("TOKENOPS_URL", "http://tokenops:7700")
    assert should_mount_run_registration() is False


def test_agent_skips_mount_when_should_mount_is_false(tmp_path):
    """The (now-dead, since should_mount_run_registration() is always False)
    if should_mount_run_registration(): mount_run_registration(...) call sites in the
    example servers must not expose POST /v1/runs."""
    store = Store(str(tmp_path / "r.db"))
    app = FastAPI()
    if should_mount_run_registration():
        mount_run_registration(app, store)
    with TestClient(app) as client:
        resp = client.post("/v1/runs", json={"intent": "x", "user_dims": {}})
        assert resp.status_code == 404
    store.close()


def test_mount_run_registration_still_works_when_called_directly(tmp_path):
    """mount_run_registration() itself is unconditional — a standalone deployment
    (src/tokenops/server) can still call it directly without going through
    should_mount_run_registration()."""
    store = Store(str(tmp_path / "e.db"))
    app = FastAPI()
    mount_run_registration(app, store)
    with TestClient(app) as client:
        resp = client.post("/v1/runs", json={"intent": "x", "user_dims": {}})
        assert resp.status_code == 201
        assert "run_id" in resp.json()
    store.close()
