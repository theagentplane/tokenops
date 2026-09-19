"""Ledger(backend=...) — the LedgerBackend-routed write/read path (tokenops#118).

Mirrors test_ledger.py's assertions but backed by the real in-process control plane
instead of the in-memory / Store path, proving record/admit/complete/mark_halted/clear_halt and every
LedgerView read produce the same answers when routed through apply_events/read_state.
"""

from __future__ import annotations

import pytest

from conftest import make_attr, toy_price
from tokenops.control.core import Observation, Usage
from tokenops.control.ledger import RUN_TOTAL_BUDGET, UNLIMITED_LEFT, Budget, Ledger, segment_key
from tokenops.control.ledger_backend import PrecheckRequest


def _ledger(backend):
    cap = Budget(budget_id="run_llm_cap", limit_micros=1_000_000, dimension="run")
    return Ledger(budgets=[cap], price=toy_price, backend=backend), cap, backend


def _halt_state(backend, run_id):
    st = backend.read_state(PrecheckRequest(run_id=run_id, want=["halt"]))
    return st.halted, st.halt_reason


def test_store_and_backend_are_mutually_exclusive(plane_backend):
    with pytest.raises(ValueError):
        Ledger(store=object(), backend=plane_backend)


def test_pricing_and_cum_spent_via_backend(plane_backend):
    ledger, _cap, _backend = _ledger(plane_backend)
    attr = make_attr()
    ledger.open_run("run-1")

    step = ledger.record(
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
    assert step.step == 1 and step.cum_spent_micros == cost1
    assert ledger.cost_micros("run-1") == cost1


def test_zero_cost_crossing_writes_no_spend_via_backend(recording_backend):
    ledger, _cap, backend = _ledger(recording_backend)
    attr = make_attr()
    ledger.open_run("run-1")
    ledger.record(
        Observation(
            attr=attr,
            node_type="tool",
            boundary_id="search",
            ts=1.0,
            signature="sig",
            result_hash="rh",
        )
    )
    assert ledger.cost_micros("run-1") == 0
    # only a `step` event was applied — no spent_add touched the budget
    assert [e for e in backend.events if e["kind"] == "spent_add"] == []


def test_budget_left_via_backend(plane_backend):
    ledger, cap, _backend = _ledger(plane_backend)
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
    spent = 100 * 10 + 10 * 30
    sk = segment_key(attr, cap)
    assert ledger.budget_left(cap.budget_id, sk) == cap.limit_micros - spent
    assert ledger.budget_left(RUN_TOTAL_BUDGET.budget_id, f"run:{attr.run_id}") == UNLIMITED_LEFT
    assert ledger.budget_left("unknown-budget", sk) == 0


def test_admit_complete_inflight_via_backend(plane_backend):
    ledger, _cap, _backend = _ledger(plane_backend)
    ledger.open_run("run-1")
    sk = "run:run-1"
    assert ledger.inflight(sk) == 0
    ledger.admit(sk)
    ledger.admit(sk)
    assert ledger.inflight(sk) == 2
    ledger.complete(sk)
    assert ledger.inflight(sk) == 1
    ledger.complete(sk)
    ledger.complete(sk)  # floored at 0, never negative
    assert ledger.inflight(sk) == 0


def test_mark_halted_and_clear_halt_via_backend(plane_backend):
    ledger, _cap, backend = _ledger(plane_backend)
    ledger.open_run("run-1")
    assert ledger.is_halted("run-1") is False

    ledger.mark_halted("run-1", "step_cap: 2")
    assert ledger.is_halted("run-1") is True
    assert _halt_state(backend, "run-1") == (True, "step_cap: 2")

    ledger.clear_halt("run-1")
    assert ledger.is_halted("run-1") is False
    assert _halt_state(backend, "run-1") == (False, None)


def test_is_halted_sees_a_halt_set_by_another_ledger_instance(plane_backend):
    """Two Ledgers sharing one backend (simulating two processes / a shared plane) —
    a halt set on one must be visible from the other without local state."""
    cap = Budget(budget_id="run_llm_cap", limit_micros=1_000_000, dimension="run")
    ledger_a = Ledger(budgets=[cap], price=toy_price, backend=plane_backend)
    ledger_b = Ledger(budgets=[cap], price=toy_price, backend=plane_backend)

    ledger_a.mark_halted("shared-run", "cost_budget: exhausted")
    assert ledger_b.is_halted("shared-run") is True


def test_admit_complete_share_inflight_across_ledger_instances(plane_backend):
    ledger_a = Ledger(backend=plane_backend)
    ledger_b = Ledger(backend=plane_backend)
    # Run-scoped, as wrap_complete uses. The real plane rejects a key with no run_id
    # embedded (precheck 400 "run_id is required"); the old in-memory fake accepted it.
    sk = "run:shared-run"
    ledger_a.admit(sk)
    ledger_b.admit(sk)
    assert ledger_a.inflight(sk) == 2
    assert ledger_b.inflight(sk) == 2


def test_local_run_state_reads_stay_local_not_backend(plane_backend):
    """step_count/velocity/recent/window are the Tier-1 cache — per-process, never a
    backend round trip. A second Ledger sharing the same backend does NOT see them."""
    ledger_a = Ledger(price=toy_price, backend=plane_backend)
    ledger_b = Ledger(price=toy_price, backend=plane_backend)
    attr = make_attr()
    ledger_a.open_run("run-1")
    ledger_a.record(
        Observation(
            attr=attr,
            node_type="llm",
            boundary_id="chat",
            ts=1.0,
            provider="openai",
            model="gpt-4o-mini",
            usage=Usage(input=10, output=1),
        )
    )
    assert ledger_a.step_count("run-1") == 1
    assert ledger_b.step_count("run-1") == 0  # no shared Tier-1 state, by design
