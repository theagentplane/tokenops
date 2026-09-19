"""One fully-populated sample per ``LedgerEvent`` kind — the SDK's side of the wire.

Shared by two suites:

* ``tests/test_wire_samples.py`` (blocking) — every field on ``LedgerEvent`` must appear
  in a sample and have an observer (or be listed as unobservable). Add a field to the
  TypedDict and this fails until you enroll it.
* ``tests/compat`` (non-blocking) — sends each sample to a real control plane and reads
  every field back, so a plane that silently drops a field shows up as a failing case
  named after that field.

An *observer* returns ``(expected, actual)`` for one field of one kind: what the SDK sent
and what the plane now reports through a public read path (the precheck window, or
the run record for aggregates).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from tokenops.control.ledger_backend import PrecheckRequest

RUN = "run_compat"
SEG = f"run:{RUN}"
SPENT_KEY = f"run_llm_cap|{SEG}|lifetime"

#: fields every event carries; exercised by the contract suite, not per-kind here.
ENVELOPE = frozenset({"kind", "idempotency_key", "run_id", "ts"})

SAMPLES: dict[str, dict[str, Any]] = {
    "spent_add": {
        "kind": "spent_add",
        "idempotency_key": "s-spent",
        "run_id": RUN,
        "ts": 1.0,
        "delta_micros": 10_500,
        "targets": [
            {"budget_id": "__run_total__", "segment_key": SEG, "period": "lifetime"},
            {"budget_id": "run_llm_cap", "segment_key": SEG, "period": "lifetime"},
        ],
    },
    "admit": {
        "kind": "admit",
        "idempotency_key": "s-admit",
        "run_id": RUN,
        "ts": 1.0,
        "segment_key": SEG,
    },
    "complete": {
        "kind": "complete",
        "idempotency_key": "s-complete",
        "run_id": RUN,
        "ts": 1.0,
        "segment_key": SEG,
    },
    "step": {
        "kind": "step",
        "idempotency_key": "s-step",
        "run_id": RUN,
        "ts": 1.0,
        "agent": "researcher",
        "seq": 1,
        "node_type": "llm",
        "boundary_id": "researcher.chat",
        "cost_micros": 10_500,
        "cum_spent_micros": 10_500,
        "usage": {"input": 1000, "output": 500, "cached": 200, "reasoning": 50},
        "tags": {"provider": "anthropic", "model": "claude-sonnet-4-6"},
        "tool_signature": "search(q)",
        "result_hash": "abc123",
        "compaction": {"tokens_before": 12_000, "tokens_after": 8_000, "tokens_saved": 4_000},
    },
    "halt_mark": {
        "kind": "halt_mark",
        "idempotency_key": "s-halt",
        "run_id": RUN,
        "ts": 1.0,
        "reason": "step_cap: 20",
        "detector": "step_cap",
    },
}

Observer = Callable[[Any, dict[str, Any]], tuple[Any, Any]]


def _window_step(backend: Any) -> dict[str, Any]:
    win = backend.read_state(PrecheckRequest(run_id=RUN, want=["window"])).window
    return win["recent"][-1] if win and win["recent"] else {}


def _step_field(field: str) -> Observer:
    return lambda backend, ev: (ev[field], _window_step(backend).get(field))


def _spent(backend: Any, ev: dict[str, Any]) -> dict[str, int]:
    return backend.read_state(
        PrecheckRequest(run_id=RUN, budgets=ev["targets"], want=["spent"])
    ).spent


def _inflight(backend: Any) -> int:
    st = backend.read_state(PrecheckRequest(run_id=RUN, segment_keys=[SEG], want=["inflight"]))
    return st.inflight.get(SEG, 0)


def _compaction_stats(backend: Any, sent: dict[str, int]) -> dict[str, int] | None:
    """The plane's per-run ``context_compaction`` aggregate, narrowed to the keys we sent.

    One sample step means the sums equal the sample; ``calls`` is the plane's own counter.
    Returns ``None`` when the plane has no ``policy_stats`` (older than 0.2.2).
    """
    try:
        rec = backend._req("GET", f"/v1/run-records/{RUN}").json()
    except Exception:  # run record absent: the plane kept nothing
        return None
    stats = (rec.get("policy_stats") or {}).get("context_compaction")
    return None if stats is None else {k: stats.get(k) for k in sent}


def _halt(backend: Any) -> Any:
    return backend.read_state(PrecheckRequest(run_id=RUN, want=["halt"]))


OBSERVERS: dict[tuple[str, str], Observer] = {
    ("spent_add", "delta_micros"): lambda b, ev: (
        ev["delta_micros"],
        _spent(b, ev).get(SPENT_KEY),
    ),
    ("spent_add", "targets"): lambda b, ev: (
        sorted(f"{t['budget_id']}|{t['segment_key']}|{t['period']}" for t in ev["targets"]),
        sorted(k for k, v in _spent(b, ev).items() if v == ev["delta_micros"]),
    ),
    ("admit", "segment_key"): lambda b, ev: (1, _inflight(b)),
    # the compat test admits first, then completes: net inflight is back to zero
    ("complete", "segment_key"): lambda b, ev: (0, _inflight(b)),
    ("halt_mark", "reason"): lambda b, ev: (ev["reason"], _halt(b).halt_reason),
    **{
        ("step", f): _step_field(f)
        for f in (
            "agent",
            "seq",
            "node_type",
            "boundary_id",
            "cost_micros",
            "cum_spent_micros",
            "usage",
            "tags",
            "tool_signature",
            "result_hash",
        )
    },
    # Not in the step window: the plane folds it into a per-run aggregate and exposes it
    # as `policy_stats` on the run record (control-plane#18/#19, contract 0.2.2).
    ("step", "compaction"): lambda b, ev: (
        ev["compaction"],
        _compaction_stats(b, ev["compaction"]),
    ),
}

#: fields the plane accepts but exposes through no public read path. Listed so the gap is
#: visible rather than silently untested; delete the entry when a read path appears.
UNOBSERVABLE: dict[tuple[str, str], str] = {
    ("halt_mark", "detector"): "precheck returns halt_reason only",
}
