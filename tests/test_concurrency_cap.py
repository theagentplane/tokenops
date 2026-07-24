"""concurrency_cap — backpressure (QUEUE/REJECT), never a kill."""

from __future__ import annotations

from conftest import FakeView, make_attr
from tokenops.control import ActionKind, CallRequest
from tokenops.control.policies import concurrency_cap


def _req():
    return CallRequest(attr=make_attr(), provider="openai", model="gpt-4o-mini")


def test_trips_at_ceiling():
    det, _ = concurrency_cap.build(max_concurrent=3)
    assert det.pre_call(_req(), FakeView(_inflight=3)).severity.value == "trip"


def test_allows_below_ceiling():
    det, _ = concurrency_cap.build(max_concurrent=3)
    assert det.pre_call(_req(), FakeView(_inflight=2)) is None


def test_reject_mode():
    det, pol = concurrency_cap.build(max_concurrent=1, mode="reject")
    sig = det.pre_call(_req(), FakeView(_inflight=1))
    a = pol.decide(sig, FakeView())
    assert a.kind is ActionKind.REJECT and a.retry_after_s is not None


def test_queue_mode():
    det, pol = concurrency_cap.build(max_concurrent=1, mode="queue")
    sig = det.pre_call(_req(), FakeView(_inflight=1))
    assert pol.decide(sig, FakeView()).kind is ActionKind.QUEUE
