from __future__ import annotations

import pytest

from tokenops.control.run import tokenops_run
from tokenops.control.store import Store


@pytest.fixture
def store(tmp_path):
    from tokenops.control.governance_cache import clear_governance_config_cache

    clear_governance_config_cache()
    s = Store(str(tmp_path / "test.db"))
    yield s
    s.close()


def test_tokenops_run_raises_when_chronicle_is_disabled(store, monkeypatch):
    monkeypatch.setenv("CHRONICLE_ENABLED", "0")
    from tokenops.control.core import GovernanceUnavailable

    with pytest.raises(GovernanceUnavailable, match="CHRONICLE_ENABLED is off"):
        with tokenops_run(store=store, service="agent", intent="test"):
            pass


def test_tokenops_run_succeeds_when_chronicle_enabled(store, monkeypatch):
    monkeypatch.delenv("CHRONICLE_ENABLED", raising=False)
    with tokenops_run(store=store, service="agent", intent="test") as bound:
        assert bound.registration is not None
