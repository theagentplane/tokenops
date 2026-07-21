"""HTTP tests for the standalone control-plane FastAPI app."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

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


def test_research_skips_mount_when_tokenops_url(monkeypatch, tmp_path):
    """With TOKENOPS_URL set, research must not expose POST /v1/runs."""
    monkeypatch.setenv("TOKENOPS_DB", str(tmp_path / "r.db"))
    monkeypatch.setenv("TOKENOPS_URL", "http://tokenops:7700")
    monkeypatch.delenv("TOKENOPS_EMBEDDED", raising=False)

    from bench.agents.research.native import server as srv

    app = srv.build_app()
    with TestClient(app) as client:
        resp = client.post("/v1/runs", json={"intent": "x", "user_dims": {}})
        assert resp.status_code == 404
