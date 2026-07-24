"""Ledger (Design A) — accounting, window, and the LedgerView reads."""

from __future__ import annotations

import pytest

from conftest import make_attr, toy_price
from tokenops.control.core import Observation, Usage
from tokenops.control.ledger import RUN_TOTAL_BUDGET, UNLIMITED_LEFT, Budget, Ledger, segment_key


def _ledger():
    cap = Budget(budget_id="run_llm_cap", limit_micros=1_000_000, dimension="run")
    return Ledger(budgets=[cap], price=toy_price), cap


def test_pricing_and_cum_spent_single_source():
    ledger, cap = _ledger()
    attr = make_attr()
    ledger.open_run("run-1")

    s1 = ledger.record(
        Observation(
            attr=attr,
            node_type="llm",
            boundary_id="chat",
            ts=1.0,
            provider="openai",
            model="gpt-4o-mini",
            usage=Usage(input=820, output=45),
        )
    )
    cost1 = 820 * 10 + 45 * 30
    assert s1.step == 1 and s1.cum_spent_micros == cost1
    # cum_spent is READ from the canonical run accumulator (single source of truth)
    assert ledger.cost_micros("run-1") == cost1


def test_tool_and_delegate_costs():
    ledger, _ = _ledger()
    attr = make_attr()
    ledger.open_run("run-1")
    ledger.record(
        Observation(
            attr=attr,
            node_type="llm",
            boundary_id="chat",
            ts=1.0,
            provider="openai",
            model="gpt-4o-mini",
            usage=Usage(input=100, output=10),
        )
    )
    before = ledger.cost_micros("run-1")
    ledger.record(
        Observation(
            attr=attr,
            node_type="tool",
            boundary_id="search",
            ts=2.0,
            signature="sig",
            result_hash="rh",
        )
    )
    assert ledger.cost_micros("run-1") == before, "tool call must not move spend"
    ledger.record(
        Observation(
            attr=attr, node_type="delegate", boundary_id="d", ts=3.0, rolled_up_cost_micros=25_000
        )
    )
    assert ledger.cost_micros("run-1") == before + 25_000


def test_velocity_and_recent():
    ledger, _ = _ledger()
    attr = make_attr()
    ledger.open_run("run-1")
    for i in range(1, 4):
        ledger.record(
            Observation(
                attr=attr,
                node_type="llm",
                boundary_id="chat",
                ts=float(i),
                provider="openai",
                model="gpt-4o-mini",
                usage=Usage(input=100, output=0),
            )
        )
    win = ledger.window("run-1")
    assert ledger.velocity("run-1", 3) == (win[-1].cum_spent_micros - win[-3].cum_spent_micros) / 3
    assert [s.step for s in ledger.recent("run-1", 2)] == [2, 3]


def test_budget_left_real_cap_and_unlimited_run_total():
    ledger, cap = _ledger()
    attr = make_attr()
    ledger.open_run("run-1")
    ledger.record(
        Observation(
            attr=attr,
            node_type="llm",
            boundary_id="chat",
            ts=1.0,
            provider="openai",
            model="gpt-4o-mini",
            usage=Usage(input=1000, output=0),
        )
    )
    assert ledger.budget_left("run_llm_cap", segment_key(attr, cap)) == 1_000_000 - 10_000
    assert (
        ledger.budget_left("__run_total__", segment_key(attr, RUN_TOTAL_BUDGET)) == UNLIMITED_LEFT
    )


def test_inflight_admit_complete_floored():
    ledger, _ = _ledger()
    ledger.admit("run:run-1")
    ledger.admit("run:run-1")
    assert ledger.inflight("run:run-1") == 2
    for _ in range(3):
        ledger.complete("run:run-1")
    assert ledger.inflight("run:run-1") == 0


def test_halt_sticky_and_clear():
    ledger, _ = _ledger()
    ledger.open_run("run-1")
    assert not ledger.is_halted("run-1")
    ledger.mark_halted("run-1", "budget")
    assert ledger.is_halted("run-1")
    ledger.clear_halt("run-1")
    assert not ledger.is_halted("run-1")


def test_fail_closed_on_unknown_model():
    ledger, _ = _ledger()
    attr = make_attr()
    ledger.open_run("run-1")
    with pytest.raises(ValueError):
        ledger.record(
            Observation(
                attr=attr,
                node_type="llm",
                boundary_id="x",
                ts=1.0,
                provider="openai",
                model="mystery",
                usage=Usage(input=1),
            )
        )
