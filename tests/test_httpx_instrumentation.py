"""TokenOps' own control-plane calls must not be recorded by ``chronicle.instrument_httpx()``.

If they were, every governed call would record the plane call as a crossing, which re-enters the
governor hook, which calls the plane again: unbounded recursion that Chronicle swallows as a hook
failure, leaving the run ungoverned (no spend recorded, no budget trips). The behavioural
regression test is ``tests/e2e/test_triad_example.py``; this one pins the marker itself.
"""

from __future__ import annotations

from tokenops.repositories import PrecheckRequest


def test_plane_requests_carry_the_chronicle_internal_marker(fake_plane):
    client = fake_plane.client()
    client.governance("planner")
    client.precheck(PrecheckRequest(trace_id="t"))
    assert fake_plane.requests
    assert all(r.extensions.get("chronicle.internal") is True for r in fake_plane.requests)
