"""Focused tests for install_crossing_hook + on_crossing bind/unbind."""

from __future__ import annotations

from chronicle import boundary, default_hooks

from conftest import toy_price
from tokenops.control import (
    ApplyControls,
    build_governor,
    install_crossing_hook,
)
from tokenops.control.attribution import _build_attribution
from tokenops.control.context import SpanContext, _governance_scope, clear, run_scope
from tokenops.control.crossing import TokenOpsHook
from tokenops.control.models import RunRegistration


def test_install_crossing_hook_is_idempotent():
    install_crossing_hook()
    install_crossing_hook()
    assert sum(isinstance(h, TokenOpsHook) for h in default_hooks) == 1


def test_hook_is_a_default_hook_for_new_sessions():
    """Default hooks are inherited by every session, so there is nothing to re-attach."""
    install_crossing_hook()
    assert any(isinstance(h, TokenOpsHook) for h in default_hooks)


def test_on_crossing_noop_when_unbound():
    """Without governance + registration, hook must not raise or touch ledger."""
    clear()
    install_crossing_hook()

    @boundary(
        "search",
        kind="tool",
        extract_input=lambda q: {"name": "search", "args": {"query": q}},
    )
    def search(query: str) -> dict:
        return {"snippet": query}

    # Hook is registered, but governance context is empty -> no-op.
    assert search("x")["snippet"] == "x"
    clear()


def test_on_crossing_observes_when_governed():
    clear()
    install_crossing_hook()
    reg = RunRegistration(trace_id="hook-1", intent="demo")
    config = {
        "governance": {
            "budgets": [{"id": "run_llm_cap", "limit_micros": 1_000_000, "dimension": "trace"}],
            "policies": {"step_cap": {"max_steps": 100}},
        }
    }
    gov = build_governor(config, toy_price, ApplyControls())
    attr = _build_attribution(reg, service="research")
    gov.ledger.open_run("hook-1")

    @boundary(
        "search",
        kind="tool",
        extract_input=lambda q: {"name": "search", "args": {"query": q}},
    )
    def search(query: str) -> dict:
        return {"snippet": query, "completeness": 0.9}

    with run_scope(reg, SpanContext(span_id="s1", service="research")):
        with _governance_scope(gov, attr):
            search("pricing")

    clear()
    assert gov.ledger.step_count("hook-1") == 1
