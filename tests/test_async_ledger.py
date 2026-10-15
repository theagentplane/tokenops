"""The Ledger and tokenops_run with asynchronous writes (ADR 0003)."""

from __future__ import annotations

import json

import pytest

from conftest import make_attr, toy_price
from tokenops import flush_ledger_writes, tokenops_run
from tokenops.framework.config import build_governor
from tokenops.framework.core import Observation, Usage
from tokenops.framework.ledger import LIFETIME
from tokenops.repositories import LedgerEventWriter

GOV = {
    "governance": {
        "budgets": [{"id": "run_llm_cap", "limit_micros": 2_000_000, "dimension": "trace"}],
        "policies": {},
    }
}


def _obs(trace_id: str, inp: int = 100_000) -> Observation:
    return Observation(
        attr=make_attr(trace_id=trace_id),
        node_type="llm",
        boundary_id="chat",
        ts=1.0,
        provider="openai",
        model="gpt-4o-mini",
        usage=Usage(input=inp, output=0),
    )


def _events(plane) -> list[dict]:
    return [
        e
        for r in plane.requests
        if r.url.path == "/v1/ledger/events:batch"
        for e in json.loads(r.content)["events"]
    ]


@pytest.fixture
def writer_and_plane(fake_plane):
    client = fake_plane.client()
    writer = LedgerEventWriter(client, flush_interval_s=0.01)
    yield client, writer, fake_plane
    writer.close(2)


def test_spend_is_queued_and_the_trace_total_is_local(writer_and_plane):
    client, writer, plane = writer_and_plane
    gov = build_governor(GOV, toy_price, backend=client, writer=writer)
    gov.ledger.open_run("t1")

    step = gov.ledger.record(_obs("t1", inp=100_000))
    assert step.cum_spent_micros == 1_000_000  # this process's own sum, no ack needed
    assert writer.flush(5)
    assert plane.spent["__trace_total__|trace:t1|lifetime"] == 1_000_000


def test_a_read_waits_for_this_process_writes(writer_and_plane):
    """Read-your-writes: budget_left sees spend that is still queued."""
    client, writer, plane = writer_and_plane
    gov = build_governor(GOV, toy_price, backend=client, writer=writer)
    gov.ledger.open_run("t2")
    gov.ledger.record(_obs("t2", inp=190_000))

    left = gov.ledger.budget_left("run_llm_cap", "trace:t2", LIFETIME)
    assert left == 2_000_000 - 1_900_000


def test_complete_is_queued_but_admit_and_halt_are_synchronous(writer_and_plane):
    client, writer, plane = writer_and_plane
    gov = build_governor(GOV, toy_price, backend=client, writer=writer)
    gov.ledger.open_run("t3")
    seg = "trace:t3"

    gov.ledger.admit(seg)
    assert plane.inflight[seg] == 1  # visible at once: admit gates other processes
    gov.ledger.mark_halted("t3", "stop")
    assert plane.halts["t3"] == "stop"  # visible at once

    gov.ledger.complete(seg)
    assert writer.flush(5)
    assert plane.inflight[seg] == 0
    kinds = [e["kind"] for e in _events(plane)]
    assert kinds == ["admit", "halt_mark", "complete"]


def test_tokenops_run_shares_one_writer_per_client_and_flushes(fake_plane):
    fake_plane.set_governance("planner", GOV)
    client = fake_plane.client()

    with tokenops_run(client=client, service="planner", payload={}) as bound:
        writer = bound.governor.ledger._writer
        assert writer is not None
        bound.governor.ledger.record(_obs(bound.attr.trace_id, inp=1_000))
    with tokenops_run(client=client, service="planner", payload={}) as again:
        assert again.governor.ledger._writer is writer

    assert flush_ledger_writes(5)
    kinds = {e["kind"] for e in _events(fake_plane)}
    assert "spent_add" in kinds


def test_async_writes_can_be_turned_off(fake_plane):
    fake_plane.set_governance("planner", GOV)
    with tokenops_run(
        client=fake_plane.client(), service="planner", payload={}, async_writes=False
    ) as bound:
        assert bound.governor.ledger._writer is None
