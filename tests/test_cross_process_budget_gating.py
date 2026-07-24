"""Cross-process budget gating — shared SQLite ledger across independent Governor instances."""

from __future__ import annotations

from conftest import make_attr, toy_price
from tokenops.control import Observation, Usage, build_governor
from tokenops.control.ledger import LIFETIME
from tokenops.control.store import Store

GOV = {
    "governance": {
        "budgets": [{"id": "run_llm_cap", "limit_micros": 2_000_000, "dimension": "run"}],
        "policies": {},
    }
}


def _llm_obs(run_id: str = "shared-run", *, inp: int = 100_000, out: int = 0) -> Observation:
    return Observation(
        attr=make_attr(run_id=run_id),
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
    run_id = "run-1"
    sk = f"run:{run_id}"

    gov_a.ledger.open_run(run_id)
    gov_b.ledger.open_run(run_id)

    # ~$1.90 on A (190k input tokens × 10 micros)
    gov_a.ledger.record(_llm_obs(run_id, inp=190_000))

    assert gov_a.ledger.budget_left("run_llm_cap", sk, LIFETIME) == 2_000_000 - 1_900_000
    # B still sees full cap — independent in-memory accumulators
    assert gov_b.ledger.budget_left("run_llm_cap", sk, LIFETIME) == 2_000_000


def test_shared_store_ledgers_share_spend(tmp_path):
    """Two Governor instances backed by one Store share run-scoped spend."""
    db = tmp_path / "shared.db"
    store = Store(str(db), auto_seed=False)

    gov_research = build_governor(GOV, toy_price, store=store)
    gov_summarize = build_governor(GOV, toy_price, store=store)
    run_id = "shared-run"
    sk = f"run:{run_id}"

    gov_research.ledger.open_run(run_id)
    gov_summarize.ledger.open_run(run_id)

    gov_research.ledger.record(_llm_obs(run_id, inp=190_000))
    remaining_on_summarize = gov_summarize.ledger.budget_left("run_llm_cap", sk, LIFETIME)

    assert remaining_on_summarize == 2_000_000 - 1_900_000
    assert gov_summarize.ledger.cost_micros(run_id) == 1_900_000


def test_shared_store_exhausted_budget_visible_to_second_process(tmp_path):
    store = Store(str(tmp_path / "exhaust.db"), auto_seed=False)
    gov_a = build_governor(GOV, toy_price, store=store)
    gov_b = build_governor(GOV, toy_price, store=store)
    run_id = "cap-run"
    sk = f"run:{run_id}"

    gov_a.ledger.open_run(run_id)
    gov_b.ledger.open_run(run_id)

    # Exhaust the $2.00 cap on process A
    gov_a.ledger.record(_llm_obs(run_id, inp=200_000))

    assert gov_a.ledger.budget_left("run_llm_cap", sk, LIFETIME) <= 0
    assert gov_b.ledger.budget_left("run_llm_cap", sk, LIFETIME) <= 0


def test_shared_halt_flag_cross_process(tmp_path):
    store = Store(str(tmp_path / "halt.db"), auto_seed=False)
    gov_a = build_governor(GOV, toy_price, store=store)
    gov_b = build_governor(GOV, toy_price, store=store)
    run_id = "halt-run"

    gov_a.ledger.open_run(run_id)
    gov_a.ledger.mark_halted(run_id, "budget exhausted")

    assert gov_b.ledger.is_halted(run_id)
