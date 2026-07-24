"""build_governor — declarative config → wired Governor + Ledger, fail-closed."""

from __future__ import annotations

import pytest

from conftest import make_attr, toy_price
from tokenops.control import Halt, Observation, Usage, build_governor

CONFIG = {
    "governance": {
        "budgets": [
            {"id": "run_llm_cap", "limit_micros": 20_000, "dimension": "run"},
        ],
        "policies": {
            "cost_budget": {"budget": "run_llm_cap"},
            "step_cap": {"max_steps": 50},
            "tool_output_cap": {"cap_tokens": 8000},
            "output_runaway": {"repeats": 4},
        },
    }
}


def test_builds_and_registers_all_policies():
    gov = build_governor(CONFIG, toy_price)
    assert set(gov._policy_by_name) == {
        "cost_budget",
        "step_cap",
        "tool_output_cap",
        "output_runaway",
    }
    # the budget the config declared is in the ledger
    assert gov.ledger.budget_left("run_llm_cap", "run:run-1") == 20_000


def test_e2e_cost_budget_from_config_halts():
    gov = build_governor(CONFIG, toy_price)
    attr = make_attr()
    gov.ledger.open_run("run-1")

    def llm():
        gov.observe(
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

    llm()
    llm()
    with pytest.raises(Halt):
        llm()
    assert gov.ledger.is_halted("run-1")


def test_unknown_policy_fails_closed():
    bad = {"governance": {"budgets": [], "policies": {"nonsense": {}}}}
    with pytest.raises(ValueError, match="unknown policy"):
        build_governor(bad, toy_price)


def test_missing_budget_reference_fails_closed():
    bad = {"governance": {"budgets": [], "policies": {"cost_budget": {"budget": "ghost"}}}}
    with pytest.raises(ValueError, match="unknown budget"):
        build_governor(bad, toy_price)
