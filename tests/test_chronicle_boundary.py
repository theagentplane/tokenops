"""Chronicle-compatible @boundary — record, replay stub, TokenOps ingest."""

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


def test_chronicle_live_records_envelope(chronicle_envelopes):
    @boundary("search", kind="tool")
    def search(q: str) -> dict:
        return {"snippet": q, "status": "ok"}

    out = search("pricing")
    assert out["snippet"] == "pricing"
    assert len(chronicle_envelopes) == 1
    assert chronicle_envelopes[0].name == "search"


def test_boundary_tokenops_observe_when_governed():
    clear()
    reg = HopAttribution(trace_id="r1")
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
