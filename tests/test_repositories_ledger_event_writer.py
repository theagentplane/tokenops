"""The background ledger writer: ordering, batching, and the no-double-count retry rule."""

from __future__ import annotations

import json
import threading

import httpx

from fake_plane import FakePlane
from tokenops.repositories import ControlPlaneClient, LedgerEvent, LedgerEventWriter

TARGET = {"budget_id": "b", "segment_key": "trace:t", "period": "lifetime"}


def _spend(delta: int, trace: str = "t") -> LedgerEvent:
    return {"kind": "spent_add", "trace_id": trace, "delta_micros": delta, "targets": [TARGET]}


def _writer(plane: FakePlane, **kwargs) -> LedgerEventWriter:
    kwargs.setdefault("flush_interval_s", 0.01)
    kwargs.setdefault("retry_backoff_s", 0.001)
    return LedgerEventWriter(plane.client(), **kwargs)


def test_events_are_sent_in_order_and_batched():
    plane = FakePlane()
    writer = _writer(plane, batch_size=3)
    accepted = writer.submit([_spend(i) for i in range(1, 8)])
    assert accepted == 7
    assert writer.flush(5)

    assert plane.spent["b|trace:t|lifetime"] == sum(range(1, 8))
    batches = [
        json.loads(r.content)["events"]
        for r in plane.requests
        if r.url.path == "/v1/ledger/events:batch"
    ]
    flat = [e["delta_micros"] for batch in batches for e in batch]
    assert flat == list(range(1, 8))
    assert all(len(b) <= 3 for b in batches)
    assert writer.stats.sent == 7 and writer.stats.dropped == 0


def test_submit_does_not_wait_for_the_plane():
    plane = FakePlane()
    release = threading.Event()
    real = plane.handle

    def slow(request: httpx.Request) -> httpx.Response:
        release.wait(5)
        return real(request)

    client = ControlPlaneClient("http://fake", transport=httpx.MockTransport(slow))
    writer = LedgerEventWriter(client, flush_interval_s=0.01)
    writer.submit([_spend(1)])  # returns at once although the plane is blocked
    assert plane.spent["b|trace:t|lifetime"] == 0
    release.set()
    assert writer.flush(5)
    assert plane.spent["b|trace:t|lifetime"] == 1


def test_a_failed_connect_is_retried_and_counted_once():
    plane = FakePlane()
    plane.down = True
    writer = _writer(plane, connect_retries=3)
    writer.submit([_spend(10)])

    def heal() -> None:
        while len([r for r in plane.requests if r.url.path.endswith("events:batch")]) < 2:
            pass
        plane.down = False

    threading.Thread(target=heal, daemon=True).start()
    assert writer.flush(5)
    assert plane.spent["b|trace:t|lifetime"] == 10  # applied exactly once
    assert writer.stats.sent == 1 and writer.stats.dropped == 0


def test_an_unreachable_plane_drops_after_the_bounded_retries():
    plane = FakePlane()
    plane.down = True
    drops: list[tuple[int, str]] = []
    writer = _writer(plane, connect_retries=2, on_drop=lambda n, why: drops.append((n, why)))
    writer.submit([_spend(5), _spend(6)])
    assert writer.flush(5)

    attempts = [r for r in plane.requests if r.url.path.endswith("events:batch")]
    assert len(attempts) == 3  # first try + 2 retries
    assert writer.stats.dropped_unreachable == 2
    assert drops == [(2, "unreachable")]


def test_an_unknown_outcome_is_never_retried():
    """A read timeout may have been applied: retrying could double count."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("response lost", request=request)

    client = ControlPlaneClient("http://fake", transport=httpx.MockTransport(handler))
    writer = LedgerEventWriter(client, flush_interval_s=0.01, connect_retries=5)
    writer.submit([_spend(1)])
    assert writer.flush(5)
    assert calls["n"] == 1
    assert writer.stats.dropped_unknown_outcome == 1
    assert writer.stats.sent == 0


def test_a_5xx_is_an_unknown_outcome_and_a_4xx_is_a_rejection():
    seen = iter([httpx.Response(503), httpx.Response(400, json={"detail": "bad"})])

    def handler(request: httpx.Request) -> httpx.Response:
        return next(seen)

    client = ControlPlaneClient("http://fake", transport=httpx.MockTransport(handler))
    writer = LedgerEventWriter(client, flush_interval_s=0.01, batch_size=1)
    writer.submit([_spend(1)])
    writer.flush(5)
    writer.submit([_spend(2)])
    writer.flush(5)
    assert writer.stats.dropped_unknown_outcome == 1
    assert writer.stats.dropped_rejected == 1


def test_a_full_queue_drops_new_events_without_blocking():
    plane = FakePlane()
    release = threading.Event()
    real = plane.handle

    def blocked(request: httpx.Request) -> httpx.Response:
        release.wait(5)
        return real(request)

    client = ControlPlaneClient("http://fake", transport=httpx.MockTransport(blocked))
    writer = LedgerEventWriter(client, flush_interval_s=0.01, max_queue=2, batch_size=1)
    writer.submit([_spend(1)])  # taken by the worker, which then blocks on the plane
    while writer._queue.qsize():  # noqa: SLF001 - wait for the worker to take it
        pass
    accepted = writer.submit([_spend(2), _spend(3), _spend(4), _spend(5)])
    assert accepted == 2
    assert writer.stats.dropped_queue_full == 2
    release.set()
    assert writer.flush(5)


def test_a_closed_writer_drops_instead_of_raising():
    plane = FakePlane()
    writer = _writer(plane)
    assert writer.close(5)
    assert writer.submit([_spend(1)]) == 0
    assert writer.stats.dropped_queue_full == 1
