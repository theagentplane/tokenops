"""``HttpLedgerBackend`` against a real in-process ``control_plane.app``.

There is no fake plane: the SDK's ledger tests run against the real thing, so the two
cannot drift apart. What the SDK sends versus what the plane keeps, field by field, is
``tests/compat`` (non-blocking in CI).
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
        "run_id": RUN,
        "delta_micros": delta,
        "targets": [
            {"budget_id": "__run_total__", "segment_key": SEG, "period": "lifetime"},
            {"budget_id": "run_llm_cap", "segment_key": SEG, "period": "lifetime"},
        ],
    }


def _precheck() -> PrecheckRequest:
    return PrecheckRequest(
        run_id=RUN,
        segment_keys=[SEG],
        budgets=[{"budget_id": "run_llm_cap", "segment_key": SEG, "period": "lifetime"}],
        want=["spent", "inflight", "halt"],
    )


def test_spent_add_fan_out_and_totals(plane_backend):
    res = plane_backend.apply_events([_spent_add("k1", 10_500)])
    assert res.accepted == 1 and res.deduped == 0
    assert res.totals["run_llm_cap|run:run_1|lifetime"] == 10_500
    assert res.totals["__run_total__|run:run_1|lifetime"] == 10_500


def test_in_order_accumulation(plane_backend):
    plane_backend.apply_events([_spent_add("a", 10_500), _spent_add("b", 4_800)])
    st = plane_backend.read_state(_precheck())
    assert st.spent["run_llm_cap|run:run_1|lifetime"] == 15_300


def test_idempotent_replay(plane_backend):
    plane_backend.apply_events([_spent_add("dup", 10_500)])
    res = plane_backend.apply_events([_spent_add("dup", 10_500)])
    assert res.accepted == 0 and res.deduped == 1
    assert res.totals["run_llm_cap|run:run_1|lifetime"] == 10_500


def test_admit_complete(plane_backend):
    ev = lambda k, kind: {  # noqa: E731
        "kind": kind,
        "idempotency_key": k,
        "run_id": RUN,
        "segment_key": SEG,
    }
    plane_backend.apply_events([ev("i1", "admit"), ev("i2", "admit")])
    assert plane_backend.read_state(_precheck()).inflight[SEG] == 2
    plane_backend.apply_events([ev("i3", "complete")])
    assert plane_backend.read_state(_precheck()).inflight[SEG] == 1


def test_step_window(plane_backend):
    step = lambda seq, cum: {  # noqa: E731
        "kind": "step",
        "idempotency_key": f"{RUN}:a:{seq}:step",
        "run_id": RUN,
        "agent": "a",
        "seq": seq,
        "node_type": "llm",
        "boundary_id": "a.chat",
        "cost_micros": 10_500,
        "cum_spent_micros": cum,
        "ts": float(seq),
    }
    plane_backend.apply_events([step(1, 10_500), step(2, 21_000)])
    win = plane_backend.read_state(PrecheckRequest(run_id=RUN, want=["window"])).window
    assert win["step_count"] == 2
    assert len(win["recent"]) == 2
    assert win["velocity_micros_per_step"] == 10_500.0


def test_halt_mark_visible(plane_backend):
    plane_backend.apply_events(
        [
            {
                "kind": "halt_mark",
                "idempotency_key": "h",
                "run_id": RUN,
                "reason": "step_cap: 20",
                "detector": "step_cap",
            }
        ]
    )
    st = plane_backend.read_state(PrecheckRequest(run_id=RUN, want=["halt"]))
    assert st.halted is True and st.halt_reason == "step_cap: 20"


def test_unknown_kind_raises(plane_backend):
    with pytest.raises(Exception):  # noqa: B017 - Fake: ValueError, Http: HTTPStatusError
        plane_backend.apply_events([{"kind": "bogus", "idempotency_key": "x", "run_id": RUN}])


def test_missing_idempotency_key_raises(plane_backend):
    with pytest.raises(Exception):  # noqa: B017
        plane_backend.apply_events(
            [{"kind": "spent_add", "run_id": RUN, "delta_micros": 1, "targets": []}]
        )


def test_register_resolve_roundtrip(plane_backend):
    reg = plane_backend.register_run(intent="demo", user_dims={"user_id": "alice"}, run_id=RUN)
    assert reg.run_id == RUN and reg.user_dims == {"user_id": "alice"}
    assert plane_backend.resolve_run(RUN).intent == "demo"


def test_register_twice_conflicts(plane_backend):
    plane_backend.register_run(intent="demo", run_id=RUN)
    with pytest.raises(RunAlreadyRegisteredError):
        plane_backend.register_run(intent="demo", run_id=RUN)


def test_resolve_unknown_raises(plane_backend):
    with pytest.raises(RunNotRegisteredError):
        plane_backend.resolve_run("nope")


def test_patch_run_record_drops_derived(plane_backend):
    plane_backend.register_run(intent="demo", run_id=RUN)
    # must not raise even though steps/cost_micros are passed
    plane_backend.patch_run_record(RUN, status="completed", steps=99, cost_micros=123)
