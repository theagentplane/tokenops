"""Governance config cache (§10) — hit / miss / invalidate."""

from __future__ import annotations

import pytest

from tokenops.control.client import ControlPlaneClient
from tokenops.control.governance_cache import (
    clear_governance_config_cache,
    governance_config_cache_size,
)
from tokenops.control.models import PolicyInstance
from tokenops.control.store import Store


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_governance_config_cache()
    yield
    clear_governance_config_cache()


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "gov_cache.db"), auto_seed=False)
    s.upsert_policy_instance(
        PolicyInstance(id="p1", template="step_cap", params={"max_steps": 3}, agent="planner"),
    )
    yield s
    s.close()


def test_governance_config_cache_miss_then_hit(store, monkeypatch):
    calls = {"n": 0}
    real = store._assemble_governance_config

    def counting(agent: str):
        calls["n"] += 1
        return real(agent)

    monkeypatch.setattr(store, "_assemble_governance_config", counting)

    cfg1 = store.governance_config_for("planner")
    assert calls["n"] == 1
    assert "step_cap" in cfg1["governance"]["policies"]
    assert governance_config_cache_size() == 1

    cfg2 = store.governance_config_for("planner")
    assert calls["n"] == 1  # cache hit
    assert cfg2 == cfg1
    # Returned copies are independent.
    cfg2["governance"]["policies"]["step_cap"]["max_steps"] = 99
    cfg3 = store.governance_config_for("planner")
    assert cfg3["governance"]["policies"]["step_cap"]["max_steps"] == 3


def test_clear_governance_config_cache_forces_reload(store, monkeypatch):
    calls = {"n": 0}
    real = store._assemble_governance_config

    def counting(agent: str):
        calls["n"] += 1
        return real(agent)

    monkeypatch.setattr(store, "_assemble_governance_config", counting)

    store.governance_config_for("planner")
    store.governance_config_for("planner")
    assert calls["n"] == 1

    clear_governance_config_cache()
    store.governance_config_for("planner")
    assert calls["n"] == 2


def test_upsert_invalidates_cache(store, monkeypatch):
    calls = {"n": 0}
    real = store._assemble_governance_config

    def counting(agent: str):
        calls["n"] += 1
        return real(agent)

    monkeypatch.setattr(store, "_assemble_governance_config", counting)

    store.governance_config_for("planner")
    assert calls["n"] == 1

    store.upsert_policy_instance(
        PolicyInstance(id="p1", template="step_cap", params={"max_steps": 9}, agent="planner"),
    )
    cfg = store.governance_config_for("planner")
    assert calls["n"] == 2
    assert cfg["governance"]["policies"]["step_cap"]["max_steps"] == 9


def test_client_governance_config_for_uses_cache(tmp_path, monkeypatch):
    db = str(tmp_path / "client_cache.db")
    monkeypatch.setenv("TOKENOPS_DB", db)
    monkeypatch.setenv("TOKENOPS_EMBEDDED", "1")
    monkeypatch.delenv("TOKENOPS_URL", raising=False)

    store = Store(db, auto_seed=False)
    store.upsert_policy_instance(
        PolicyInstance(id="p1", template="step_cap", params={"max_steps": 2}, agent="writer"),
    )
    client = ControlPlaneClient(store=store)

    calls = {"n": 0}
    real = store._assemble_governance_config

    def counting(agent: str):
        calls["n"] += 1
        return real(agent)

    monkeypatch.setattr(store, "_assemble_governance_config", counting)

    a = client.governance_config_for("writer")
    b = client.governance_config_for("writer")
    assert calls["n"] == 1
    assert a["governance"]["policies"]["step_cap"]["max_steps"] == 2
    assert b == a
    store.close()
