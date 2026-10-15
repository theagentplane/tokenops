"""Cross-process budget gating: independent Governors sharing one control plane."""

from __future__ import annotations

from conftest import make_attr, toy_price
from tokenops.framework.config import build_governor
from tokenops.framework.core import Observation, Usage
from tokenops.framework.ledger import LIFETIME

GOV = {
    "governance": {
        "budgets": [{"id": "run_llm_cap", "limit_micros": 2_000_000, "dimension": "trace"}],
        "policies": {},
    }
}


def _llm_obs(trace_id: str = "shared-run", *, inp: int = 100_000, out: int = 0) -> Observation:
    return Observation(
        attr=make_attr(trace_id=trace_id),
        node_type="llm",
        boundary_id="chat",
        ts=1.0,
        provider="openai",
        model="gpt-4o-mini",
        usage=Usage(input=inp, output=out),
    )


def test_in_memory_ledgers_do_not_share_spend():
    """Two Ledgers without a store each get a fresh $2 cap (the pre-fix bug)."""
    gov_a = build_governor(GOV, toy_price)
    gov_b = build_governor(GOV, toy_price)
    trace_id = "run-1"
    sk = f"trace:{trace_id}"

    gov_a.ledger.open_run(trace_id)
    gov_b.ledger.open_run(trace_id)

    # ~$1.90 on A (190k input tokens × 10 micros)
    gov_a.ledger.record(_llm_obs(trace_id, inp=190_000))

    assert gov_a.ledger.budget_left("run_llm_cap", sk, LIFETIME) == 2_000_000 - 1_900_000
    # B still sees full cap — independent in-memory accumulators
    assert gov_b.ledger.budget_left("run_llm_cap", sk, LIFETIME) == 2_000_000


def test_shared_plane_ledgers_share_spend(fake_plane):
    """Two Governor instances on one control plane share trace-scoped spend."""
    gov_research = build_governor(GOV, toy_price, backend=fake_plane.client())
    gov_summarize = build_governor(GOV, toy_price, backend=fake_plane.client())
    trace_id = "shared-run"
    sk = f"trace:{trace_id}"

    gov_research.ledger.open_run(trace_id)
    gov_summarize.ledger.open_run(trace_id)

    gov_research.ledger.record(_llm_obs(trace_id, inp=190_000))
    remaining_on_summarize = gov_summarize.ledger.budget_left("run_llm_cap", sk, LIFETIME)

    assert remaining_on_summarize == 2_000_000 - 1_900_000
    assert gov_summarize.ledger.cost_micros(trace_id) == 1_900_000


def test_shared_plane_exhausted_budget_visible_to_second_process(fake_plane):
    gov_a = build_governor(GOV, toy_price, backend=fake_plane.client())
    gov_b = build_governor(GOV, toy_price, backend=fake_plane.client())
    trace_id = "cap-run"
    sk = f"trace:{trace_id}"

    gov_a.ledger.open_run(trace_id)
    gov_b.ledger.open_run(trace_id)

    # Exhaust the $2.00 cap on process A
    gov_a.ledger.record(_llm_obs(trace_id, inp=200_000))

    assert gov_a.ledger.budget_left("run_llm_cap", sk, LIFETIME) <= 0
    assert gov_b.ledger.budget_left("run_llm_cap", sk, LIFETIME) <= 0


def test_shared_halt_flag_cross_process(fake_plane):
    gov_a = build_governor(GOV, toy_price, backend=fake_plane.client())
    gov_b = build_governor(GOV, toy_price, backend=fake_plane.client())
    trace_id = "halt-run"

    gov_a.ledger.open_run(trace_id)
    gov_a.ledger.mark_halted(trace_id, "budget exhausted")

    assert gov_b.ledger.is_halted(trace_id)
    assert fake_plane.halts[trace_id] == "budget exhausted"


def test_spend_is_written_once_per_priced_crossing(fake_plane):
    """A spent_add per priced crossing and no step event (the plane stores none)."""
    import json

    gov = build_governor(GOV, toy_price, backend=fake_plane.client())
    gov.ledger.open_run("once")
    gov.ledger.record(_llm_obs("once", inp=1_000))

    batches = [
        json.loads(r.content)["events"]
        for r in fake_plane.requests
        if r.url.path == "/v1/ledger/events:batch"
    ]
    assert len(batches) == 1
    assert [e["kind"] for e in batches[0]] == ["spent_add"]
    assert "idempotency_key" not in batches[0][0]
