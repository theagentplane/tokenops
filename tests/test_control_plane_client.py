"""Unit tests for ControlPlaneClient (embedded Store path)."""

from __future__ import annotations

import pytest

from tokenops.control.client import ControlPlaneClient, should_mount_run_registration
from tokenops.control.models import GovernanceMode, RunAlreadyRegisteredError
from tokenops.control.store import Store


def test_from_env_embedded_when_no_url(monkeypatch, tmp_path):
    monkeypatch.delenv("TOKENOPS_URL", raising=False)
    monkeypatch.delenv("TOKENOPS_EMBEDDED", raising=False)
    db = str(tmp_path / "c.db")
    monkeypatch.setenv("TOKENOPS_DB", db)

    client = ControlPlaneClient.from_env()
    assert client.embedded
    assert client.url is None

    out = client.register_run(
        intent="demo",
        user_dims={"user_id": "alice"},
        mode="preview",
    )
    assert out["status"] == "registered"
    assert out["mode"] == "preview"
    assert out["run_id"]

    store = Store(db, auto_seed=False)
    reg = store.resolve_run(out["run_id"])
    assert reg.intent == "demo"
    assert reg.user_dims["user_id"] == "alice"
    assert reg.mode is GovernanceMode.PREVIEW
    store.close()


def test_from_env_embedded_flag_overrides_url(monkeypatch, tmp_path):
    monkeypatch.setenv("TOKENOPS_URL", "http://plane:7700")
    monkeypatch.setenv("TOKENOPS_EMBEDDED", "1")
    monkeypatch.setenv("TOKENOPS_DB", str(tmp_path / "e.db"))

    client = ControlPlaneClient.from_env()
    assert client.embedded
    out = client.register_run(intent="x", run_id="fixed-run")
    assert out["run_id"] == "fixed-run"


def test_from_env_remote_when_url_set(monkeypatch):
    monkeypatch.setenv("TOKENOPS_URL", "http://localhost:7700/")
    monkeypatch.delenv("TOKENOPS_EMBEDDED", raising=False)
    client = ControlPlaneClient.from_env()
    assert not client.embedded
    assert client.url == "http://localhost:7700"


def test_register_run_duplicate_raises(tmp_path):
    store = Store(str(tmp_path / "d.db"), auto_seed=False)
    client = ControlPlaneClient(store=store)
    client.register_run(intent="a", run_id="same")
    with pytest.raises(RunAlreadyRegisteredError):
        client.register_run(intent="b", run_id="same")
    store.close()


def test_should_mount_run_registration(monkeypatch):
    monkeypatch.delenv("TOKENOPS_URL", raising=False)
    monkeypatch.delenv("TOKENOPS_EMBEDDED", raising=False)
    assert should_mount_run_registration() is True

    monkeypatch.setenv("TOKENOPS_URL", "http://tokenops:7700")
    assert should_mount_run_registration() is False

    monkeypatch.setenv("TOKENOPS_EMBEDDED", "1")
    assert should_mount_run_registration() is True
