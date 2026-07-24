"""Chronicle-compatible @boundary — record, replay stub, TokenOps ingest."""

from __future__ import annotations

import chronicle.session as chronicle_session
import pytest
from chronicle import InputState, ReplayPlan, boundary, get_session
from chronicle.session import SessionMode

from conftest import toy_price
from tokenops.control import ApplyControls, build_governor, install_crossing_hook
from tokenops.control.attribution import _build_attribution
from tokenops.control.context import SpanContext, _governance_scope, clear, run_scope
from tokenops.control.models import RunRegistration
from tokenops.control.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "c.db"))
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _crossing_hook():
    install_crossing_hook()


def test_chronicle_live_records_envelope():
    chronicle_session.reset_session()
    session = get_session()
    assert session.mode == SessionMode.LIVE

    @boundary("search", kind="tool")
    def search(q: str) -> dict:
        return {"snippet": q, "status": "ok"}

    out = search("pricing")
    assert out["snippet"] == "pricing"
    assert len(session.recorded_envelopes) == 1
    assert session.recorded_envelopes[0].node_id == "search"
    chronicle_session.reset_session()


def test_chronicle_replay_stub_skips_execution(tmp_path):
    trace_dir = tmp_path / "trace"

    chronicle_session.reset_session()
    session = get_session()
    session.begin_trace("trace-replay")

    @boundary("search", kind="tool")
    def search(q: str) -> dict:
        return {"snippet": q, "status": "ok"}

    search("record-me")
    session.export_trace(trace_dir)
    chronicle_session.reset_session()

    session = get_session()
    session.enable_replay(ReplayPlan().stub("search", 1))
    session.load_trace(trace_dir)

    called = []

    @boundary("search", kind="tool")
    def search_replay(q: str) -> dict:
        called.append(q)
        return {"snippet": "live", "status": "ok"}

    out = search_replay("ignored")
    assert out["snippet"] == "record-me"
    assert called == []
    chronicle_session.reset_session()


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
