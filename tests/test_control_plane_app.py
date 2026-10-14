"""HTTP tests for run-registration mounting on an agent app."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tokenops.control.client import should_mount_run_registration
from tokenops.control.http import mount_run_registration
from tokenops.control.store import Store


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
    """mount_run_registration() itself is unconditional — a caller can still call it directly without going through
    should_mount_run_registration()."""
    store = Store(str(tmp_path / "e.db"))
    app = FastAPI()
    mount_run_registration(app, store)
    with TestClient(app) as client:
        resp = client.post("/v1/runs", json={"intent": "x", "user_dims": {}})
        assert resp.status_code == 201
        assert "run_id" in resp.json()
    store.close()
