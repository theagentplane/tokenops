"""@boundary decorator — governed ingest (see test_chronicle_boundary for Chronicle parity)."""

from __future__ import annotations

import pytest
from chronicle import boundary

from conftest import toy_price
from tokenops.capabilities.crossing import install_crossing_hook
from tokenops.framework.attribution import _build_attribution
from tokenops.framework.config import build_governor
from tokenops.framework.context import SpanContext, _governance_scope, clear, run_scope
from tokenops.framework.engine import ApplyControls
from tokenops.framework.models import HopAttribution


@pytest.fixture(autouse=True)
def _crossing_hook():
    install_crossing_hook()


def test_boundary_emits_observation_when_governed():
    clear()
    reg = HopAttribution(trace_id="r1", intent="demo")
    config = {
        "governance": {
            "budgets": [{"id": "run_llm_cap", "limit_micros": 1_000_000, "dimension": "trace"}],
            "policies": {"step_cap": {"max_steps": 100}},
        }
    }
    gov = build_governor(config, toy_price, ApplyControls())
    attr = _build_attribution(reg, service="research")
    gov.ledger.open_run("r1")

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

    assert gov.ledger.step_count("r1") == 1
