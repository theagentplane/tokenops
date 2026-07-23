"""@boundary decorator — governed ingest (see test_chronicle_boundary for Chronicle parity)."""

from __future__ import annotations

import pytest
import chronicle.session as chronicle_session
from chronicle import InputState, boundary

from tokenops.control import ApplyControls, build_governor, install_crossing_hook
from tokenops.control.attribution import _build_attribution
from tokenops.control.context import SpanContext, clear, _governance_scope, run_scope
from tokenops.control.models import RunRegistration
from tokenops.control.store import Store
from conftest import toy_price


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "attr.db"))
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _crossing_hook():
    install_crossing_hook()


def test_boundary_emits_observation_when_governed(store):
    clear()
    reg = store.register_run(RunRegistration(run_id="r1", intent="demo"))
    config = {
        "governance": {
            "budgets": [{"id": "run_llm_cap", "limit_micros": 1_000_000, "dimension": "run"}],
            "policies": {"step_cap": {"max_steps": 100}},
        }
    }
    gov = build_governor(config, toy_price, ApplyControls())
    attr = _build_attribution(reg, service="research")
    gov.ledger.open_run("r1")
    chronicle_session.reset_session().begin_trace("r1")

    @boundary(
        "search",
        kind="tool",
        extract_input=lambda q: InputState(
            messages=[], graph_state={"name": "search", "args": {"query": q}}
        ),
    )
    def search(query: str) -> dict:
        return {"snippet": query, "completeness": 0.9}

    with run_scope(reg, SpanContext(span_id="s1", service="research")):
        with _governance_scope(gov, attr):
            search("pricing")
    clear()
    chronicle_session.reset_session()

    assert gov.ledger.step_count("r1") == 1
