"""Focused tests for install_crossing_hook + on_crossing bind/unbind."""

from __future__ import annotations

import chronicle.session as chronicle_session
from chronicle import InputState, boundary, get_session
from chronicle.session import ChronicleSession

from conftest import toy_price
from tokenops.control import (
    ApplyControls,
    build_governor,
    install_crossing_hook,
    on_crossing,
)
from tokenops.control.attribution import _build_attribution
from tokenops.control.context import SpanContext, _governance_scope, clear, run_scope
from tokenops.control.crossing import _attach
from tokenops.control.models import RunRegistration
from tokenops.control.store import Store


def test_install_crossing_hook_is_idempotent():
    install_crossing_hook()
    first = chronicle_session.reset_session
    install_crossing_hook()
    second = chronicle_session.reset_session
    assert first is second
    assert getattr(first, "_tokenops_crossing_hook", False)


def test_reset_session_reattaches_on_crossing():
    install_crossing_hook()
    session = chronicle_session.reset_session()
    assert session.on_crossing is on_crossing
    again = chronicle_session.reset_session()
    assert again is not session
    assert again.on_crossing is on_crossing


def test_on_crossing_noop_when_unbound():
    """Without governance + registration, hook must not raise or touch ledger."""
    clear()
    install_crossing_hook()
    session = chronicle_session.reset_session()
    session.begin_trace("unbound")

    @boundary(
        "search",
        kind="tool",
        extract_input=lambda q: InputState(
            messages=[], graph_state={"name": "search", "args": {"query": q}}
        ),
    )
    def search(query: str) -> dict:
        return {"snippet": query}

    # Bound session hook is set, but governance context is empty → no-op.
    assert get_session().on_crossing is on_crossing
    assert search("x")["snippet"] == "x"
    clear()
    chronicle_session.reset_session()


def test_on_crossing_observes_when_governed(tmp_path):
    clear()
    install_crossing_hook()
    store = Store(str(tmp_path / "hook.db"))
    reg = store.register_run(RunRegistration(run_id="hook-1", intent="demo"))
    config = {
        "governance": {
            "budgets": [{"id": "run_llm_cap", "limit_micros": 1_000_000, "dimension": "run"}],
            "policies": {"step_cap": {"max_steps": 100}},
        }
    }
    gov = build_governor(config, toy_price, ApplyControls())
    attr = _build_attribution(reg, service="research")
    gov.ledger.open_run("hook-1")
    chronicle_session.reset_session().begin_trace("hook-1")

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
    store.close()
    assert gov.ledger.step_count("hook-1") == 1


def test_attach_sets_handler_on_fresh_session():
    session = ChronicleSession()
    assert session.on_crossing is None
    _attach(session)
    assert session.on_crossing is on_crossing
