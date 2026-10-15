"""Verified-fake contract suite.

Every assertion runs against BOTH backends (``any_backend`` is parametrised over the
in-memory ``FakeLedgerBackend`` and a real ``control_plane.app`` over ASGI). If the fake
drifts from the plane, this file fails.
"""

from __future__ import annotations

import pytest

from tokenops.control.ledger_backend import PrecheckRequest
from tokenops.control.models import RunAlreadyRegisteredError, RunNotRegisteredError

RUN = "run_1"
SEG = f"run:{RUN}"


def _spent_add(key: str, delta: int) -> dict:
    return {
        "kind": "spent_add",
        "idempotency_key": key,
        "trace_id": RUN,
        "delta_micros": delta,
        "targets": [
            {"budget_id": "__run_total__", "segment_key": SEG, "period": "lifetime"},
            {"budget_id": "run_llm_cap", "segment_key": SEG, "period": "lifetime"},
        ],
    }


def _precheck() -> PrecheckRequest:
    return PrecheckRequest(
        trace_id=RUN,
        segment_keys=[SEG],
        budgets=[{"budget_id": "run_llm_cap", "segment_key": SEG, "period": "lifetime"}],
        want=["spent", "inflight", "halt"],
    )


def test_spent_add_fan_out_and_totals(any_backend):
    res = any_backend.apply_events([_spent_add("k1", 10_500)])
    assert res.accepted == 1 and res.deduped == 0
    assert res.totals["run_llm_cap|run:run_1|lifetime"] == 10_500
    assert res.totals["__run_total__|run:run_1|lifetime"] == 10_500


def test_in_order_accumulation(any_backend):
    any_backend.apply_events([_spent_add("a", 10_500), _spent_add("b", 4_800)])
    st = any_backend.read_state(_precheck())
    assert st.spent["run_llm_cap|run:run_1|lifetime"] == 15_300


def test_idempotent_replay(any_backend):
    any_backend.apply_events([_spent_add("dup", 10_500)])
    res = any_backend.apply_events([_spent_add("dup", 10_500)])
    assert res.accepted == 0 and res.deduped == 1
    assert res.totals["run_llm_cap|run:run_1|lifetime"] == 10_500


def test_admit_complete(any_backend):
    ev = lambda k, kind: {  # noqa: E731
        "kind": kind,
        "idempotency_key": k,
        "trace_id": RUN,
        "segment_key": SEG,
    }
    any_backend.apply_events([ev("i1", "admit"), ev("i2", "admit")])
    assert any_backend.read_state(_precheck()).inflight[SEG] == 2
    any_backend.apply_events([ev("i3", "complete")])
    assert any_backend.read_state(_precheck()).inflight[SEG] == 1


def test_step_window(any_backend):
    step = lambda seq, cum: {  # noqa: E731
        "kind": "step",
        "idempotency_key": f"{RUN}:a:{seq}:step",
        "trace_id": RUN,
        "agent": "a",
        "seq": seq,
        "node_type": "llm",
        "boundary_id": "a.chat",
        "cost_micros": 10_500,
        "cum_spent_micros": cum,
        "ts": float(seq),
    }
    any_backend.apply_events([step(1, 10_500), step(2, 21_000)])
    win = any_backend.read_state(PrecheckRequest(trace_id=RUN, want=["window"])).window
    assert win["step_count"] == 2
    assert len(win["recent"]) == 2
    assert win["velocity_micros_per_step"] == 10_500.0


def test_halt_mark_visible(any_backend):
    any_backend.apply_events(
        [
            {
                "kind": "halt_mark",
                "idempotency_key": "h",
                "trace_id": RUN,
                "reason": "step_cap: 20",
                "detector": "step_cap",
            }
        ]
    )
    st = any_backend.read_state(PrecheckRequest(trace_id=RUN, want=["halt"]))
    assert st.halted is True and st.halt_reason == "step_cap: 20"


def test_unknown_kind_raises(any_backend):
    with pytest.raises(Exception):  # noqa: B017 - Fake: ValueError, Http: HTTPStatusError
        any_backend.apply_events([{"kind": "bogus", "idempotency_key": "x", "trace_id": RUN}])


def test_missing_idempotency_key_raises(any_backend):
    with pytest.raises(Exception):  # noqa: B017
        any_backend.apply_events(
            [{"kind": "spent_add", "trace_id": RUN, "delta_micros": 1, "targets": []}]
        )


def test_register_resolve_roundtrip(any_backend):
    reg = any_backend.register_run(intent="demo", user_dims={"user_id": "alice"}, trace_id=RUN)
    assert reg.trace_id == RUN and reg.user_dims == {"user_id": "alice"}
    assert any_backend.resolve_run(RUN).intent == "demo"


def test_register_twice_conflicts(any_backend):
    any_backend.register_run(intent="demo", trace_id=RUN)
    with pytest.raises(RunAlreadyRegisteredError):
        any_backend.register_run(intent="demo", trace_id=RUN)


def test_resolve_unknown_raises(any_backend):
    with pytest.raises(RunNotRegisteredError):
        any_backend.resolve_run("nope")


def test_patch_run_record_drops_derived(any_backend):
    any_backend.register_run(intent="demo", trace_id=RUN)
    # must not raise even though steps/cost_micros are passed
    any_backend.patch_run_record(RUN, status="completed", steps=99, cost_micros=123)
