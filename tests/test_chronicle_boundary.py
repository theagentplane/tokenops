"""Chronicle-compatible @boundary — record, replay stub, TokenOps ingest."""

from __future__ import annotations

import pytest

from tokenops.chronicle import ReplayPlan, boundary, get_session, reset_session
from tokenops.chronicle.schema import InputState
from tokenops.chronicle.session import SessionMode
from tokenops.control import ApplyControls, build_governor, build_attribution
from tokenops.control.models import RunRegistration
from tokenops.control.store import Store
from tokenops.control.context import SpanContext, clear, governance_scope, run_scope
from conftest import toy_price


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "c.db"))
    yield s
    s.close()


def test_chronicle_live_records_envelope():
    reset_session()
    session = get_session()
    assert session.mode == SessionMode.LIVE

    @boundary("search", kind="tool")
    def search(q: str) -> dict:
        return {"snippet": q, "status": "ok"}

    out = search("pricing")
    assert out["snippet"] == "pricing"
    assert len(session.recorded_envelopes) == 1
    assert session.recorded_envelopes[0].node_id == "search"
    reset_session()


def test_chronicle_replay_stub_skips_execution():
    reset_session()
    session = get_session()
    session.enable_replay(ReplayPlan().stub("search", 1))
    session.load_fixture_returns({("search", 1): {"snippet": "fixture", "status": "ok"}})

    called = []

    @boundary("search", kind="tool")
    def search(q: str) -> dict:
        called.append(q)
        return {"snippet": "live", "status": "ok"}

    out = search("ignored")
    assert out["snippet"] == "fixture"
    assert called == []
    reset_session()


def test_boundary_tokenops_observe_when_governed(store):
    clear()
    reg = store.register_run(RunRegistration(run_id="r1"))
    config = {
        "governance": {
            "budgets": [{"id": "run_llm_cap", "limit_micros": 1_000_000, "dimension": "run"}],
            "policies": {"step_cap": {"max_steps": 100}},
        }
    }
    gov = build_governor(config, toy_price, ApplyControls())
    attr = build_attribution(reg, service="research")
    gov.ledger.open_run("r1")

    reset_session().begin_trace("r1")

    @boundary(
        "search",
        kind="tool",
        extract_input=lambda q: InputState(graph_state={"name": "search", "args": {"query": q}}),
    )
    def search(query: str) -> dict:
        return {"snippet": query, "completeness": 0.9}

    with run_scope(reg, SpanContext(span_id="s1", service="research")):
        with governance_scope(gov, attr):
            search("pricing")

    clear()
    reset_session()
    assert gov.ledger.step_count("r1") == 1
