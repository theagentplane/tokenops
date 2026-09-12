"""Unit tests for ControlPlaneClient (tokenops#118: remote-only, no embedded ledger)."""

from __future__ import annotations

import pytest

from tokenops.control.client import ControlPlaneClient, should_mount_run_registration
from tokenops.control.ledger_backend import HttpLedgerBackend
from tokenops.control.models import GovernanceMode, RunAlreadyRegisteredError
from tokenops.control.store import Store


def test_from_env_raises_without_a_url(monkeypatch):
    monkeypatch.delenv("CONTROL_PLANE_URL", raising=False)
    monkeypatch.delenv("TOKENOPS_URL", raising=False)
    monkeypatch.delenv("TOKENOPS_CONTROL_PLANE_URL", raising=False)
    with pytest.raises(RuntimeError, match="CONTROL_PLANE_URL"):
        ControlPlaneClient.from_env()


def test_from_env_remote_when_url_set(monkeypatch):
    monkeypatch.setenv("TOKENOPS_URL", "http://localhost:7700/")
    client = ControlPlaneClient.from_env()
    assert not client.embedded
    assert client.url == "http://localhost:7700"
    assert isinstance(client.backend, HttpLedgerBackend)


def test_backend_raises_for_a_store_constructed_client(tmp_path):
    """The test-only store= escape hatch has no LedgerBackend — fail closed rather
    than silently returning something that would talk to a plane that isn't there."""
    store = Store(str(tmp_path / "s.db"), auto_seed=False)
    client = ControlPlaneClient(store=store)
    with pytest.raises(RuntimeError):
        _ = client.backend
    store.close()


def test_register_run_duplicate_raises(tmp_path):
    store = Store(str(tmp_path / "d.db"), auto_seed=False)
    client = ControlPlaneClient(store=store)
    client.register_run(intent="a", run_id="same")
    with pytest.raises(RunAlreadyRegisteredError):
        client.register_run(intent="b", run_id="same")
    store.close()


def test_resolve_run_and_governance_config_for(tmp_path):
    store = Store(str(tmp_path / "facade.db"), auto_seed=False)
    client = ControlPlaneClient(store=store)
    client.register_run(intent="x", run_id="r1", mode="preview")
    reg = client.resolve_run("r1")
    assert reg.intent == "x"
    assert reg.mode is GovernanceMode.PREVIEW
    cfg = client.governance_config_for("any")
    assert "governance" in cfg
    store.close()


def test_should_mount_run_registration_is_always_false(monkeypatch):
    monkeypatch.delenv("TOKENOPS_URL", raising=False)
    assert should_mount_run_registration() is False

    monkeypatch.setenv("TOKENOPS_URL", "http://tokenops:7700")
    assert should_mount_run_registration() is False
