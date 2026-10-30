"""Ledger — the Attribute module and the read-only LedgerView the policies read from.

State is exactly the LLD's three maps. They are separate on purpose: one boundary
crossing can increment *many* budget accumulators at once, so spend cannot live inside
a single run object.

    runs:     trace_id      -> LocalRunState      (per-trace ephemeral: steps, window, halted)
    spent:    (budget_id, segment_key, period) -> micros   (one budget bound to a segment)
    inflight: segment_key -> int               (concurrent calls in flight, admit/complete)

Why three maps, not fields on LocalRunState:
  * ``spent`` is budget-scoped — a tenant's monthly cap and this run's cap are two
    accumulators the *same* event feeds. Keying by run would lose that fan-out.
  * ``inflight`` is segment-scoped for concurrency only — it is admit/complete state,
    not spend, so it does not belong on a per-run object either.

Single source of spend truth (Design A): the run total is NOT a separate counter — it
lives in the ``spent`` map under a canonical, always-present run-scoped accumulator
(``TRACE_TOTAL_BUDGET``). ``cost_micros`` and each ``BoundaryStep.cum_spent_micros`` are
reads of that one accumulator, so the map is the only place spend is ever written.

Invariant — *every trace has a trace budget*: structurally guaranteed, because a
``dimension="trace"`` budget resolves a fresh ``segment_key`` per trace, so one system
budget definition covers every trace without you configuring anything.

Concurrency
-----------
One :class:`Ledger` is safe for concurrent threads. Mutations and reads of the in-memory
maps (``runs`` / ``_spent`` / ``_inflight``) are serialized on an internal RLock.

* **Different ``trace_id``s** on the same Ledger: safe; spend / steps / halt do not lose
  updates under concurrent ``record`` / ``admit`` / ``mark_halted``.
* **Same ``trace_id``**: also safe — calls serialize; halt flags are not torn. Prefer one
  writer per run when possible (typical: per-request Governor), but re-entrancy from
  multiple threads will not corrupt counters.
* **Plane-backed Ledger**: spend / inflight / halt go through the control plane
  (a :class:`~tokenops.framework.ledger_backend.LedgerBackend`). Multiple Ledgers / Governors sharing one
  plane share those accumulators; each Ledger's step window stays local to that Ledger
  instance (the plane stores no step window, control-plane ADR 0009).

See ``docs/concurrency.md``.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

from tokenops.framework.budget import (
    LIFETIME,
    TRACE_TOTAL_BUDGET,
    UNLIMITED_LEFT,
    Budget,
    Dimension,
    PriceFn,
    segment_key,
    segment_key_for,
    trace_id_from_segment_key,
)
from tokenops.framework.core import (
    BoundaryStep,
    Micros,
    Observation,
)
from tokenops.framework.ledger_backend import LedgerBackend, LedgerWriter
from tokenops.framework.ledger_events import halt_event, inflight_event, spent_add_event
from tokenops.framework.ledger_types import BudgetTarget, PrecheckRequest

__all__ = [
    "LIFETIME",
    "TRACE_TOTAL_BUDGET",
    "UNLIMITED_LEFT",
    "Budget",
    "Dimension",
    "Ledger",
    "LocalRunState",
    "PriceFn",
    "segment_key",
    "segment_key_for",
]


# =========================================================================== #
# Per-trace ephemeral state                                                      #
# =========================================================================== #


@dataclass
class LocalRunState:
    """Ephemeral per-process, per-run cache (Tier 1). The dict key in ``Ledger.runs`` is
    the trace_id — there is deliberately no trace_id field here (the index is not a field).

    This is the per-process cache in the two-tier model: cheap reads for `local`-scope
    policies without a round trip. `global`-scope policies read the plane's `run_state`
    table instead (via `precheck`), since that is authoritative across processes."""

    steps: int = 0
    window: list[BoundaryStep] = field(default_factory=list)
    halted: bool = False
    halt_reason: str | None = None
    parent_run: str | None = None
    #: Last-known run-total cum_spent from a backend ack, so a zero-cost crossing's
    #: BoundaryStep doesn't need its own read_state round trip.
    cum_spent_cache: Micros = 0


# =========================================================================== #
# The ledger (Attribute + LedgerView in one in-memory implementation)          #
# =========================================================================== #


class Ledger:
    """Attribute + LedgerView. Per-process trace state (window, local step count); spend,
    inflight, and halt may be backed by the control plane
    (a :class:`~tokenops.framework.ledger_backend.LedgerBackend`) for cross-process / cross-agent
    consistency. Without a ``backend`` it is fully in-memory (single process, tests, the
    demo).

    ``backend`` mode: every write goes through ``apply_events`` (one batch per crossing)
    and every spend/inflight/halt read goes through ``precheck``. A write is attempted
    once and never retried (ADR 0002); a failed write raises to the caller. There is no
    per-call batching across detectors yet, so a call with several ``global``-scope
    policies costs more than one ``precheck``.

    Thread-safe for concurrent use from multiple threads (see module docstring).
    """

    def __init__(
        self,
        *,
        budgets: Sequence[Budget] = (),
        price: PriceFn | None = None,
        backend: LedgerBackend | None = None,
        writer: LedgerWriter | None = None,
        barrier_timeout_s: float = 2.0,
    ) -> None:
        self._lock = threading.RLock()
        self._backend = backend
        self._writer = writer if backend is not None else None
        self._barrier_timeout = barrier_timeout_s
        self.runs: dict[str, LocalRunState] = {}
        self._spent: dict[tuple[str, str, str], Micros] = defaultdict(int)
        self._inflight: dict[str, int] = defaultdict(int)
        self._budgets: list[Budget] = [TRACE_TOTAL_BUDGET, *budgets]
        self._budget_by_id: dict[str, Budget] = {b.budget_id: b for b in self._budgets}
        self._price = price

    def _spent_key(self, budget_id: str, segment_key: str, period: str) -> tuple[str, str, str]:
        return (budget_id, segment_key, period)

    def _barrier(self) -> None:
        """Read-your-writes: wait (bounded) for this process's queued writes before a read.

        Only the already-queued events are awaited, so the wait is short; on a timeout the
        read proceeds and may be stale by the events still queued.
        """
        if self._writer is not None:
            self._writer.flush(self._barrier_timeout)

    def _read_spent(self, budget_id: str, segment_key: str, period: str) -> Micros:
        if self._backend is not None:
            self._barrier()
            state = self._backend.precheck(
                PrecheckRequest(
                    trace_id=trace_id_from_segment_key(segment_key) or "",
                    budgets=[
                        {"budget_id": budget_id, "segment_key": segment_key, "period": period}
                    ],
                    want=["spent"],
                )
            )
            return state.spent.get(f"{budget_id}|{segment_key}|{period}", 0)
        return self._spent[self._spent_key(budget_id, segment_key, period)]

    def _write_spent_delta(
        self,
        budget_id: str,
        segment_key: str,
        period: str,
        delta: Micros,
    ) -> Micros:
        # Backend mode batches spent_add into record()'s single apply_events call, so it
        # never reaches this in-memory path.
        key = self._spent_key(budget_id, segment_key, period)
        self._spent[key] += delta
        return self._spent[key]

    # ---- write side (Attribute) ------------------------------------------ #

    def open_run(self, trace_id: str, parent_run: str | None = None) -> None:
        with self._lock:
            self.runs[trace_id] = LocalRunState(parent_run=parent_run)

    def close_run(self, trace_id: str) -> None:
        """Drop the per-process :class:`LocalRunState` for a finished run. Idempotent.

        ``tokenops_run`` calls this on scope exit for the run it opened, so a
        long-lived / shared-governor process does not accumulate ``LocalRunState``
        entries (each holds a full ``window`` of ``BoundaryStep``s).
        """
        with self._lock:
            self.runs.pop(trace_id, None)

    def admit(self, segment_key: str) -> None:
        """A call for this segment has started (concurrency)."""
        with self._lock:
            if self._backend is not None:
                trace_id = trace_id_from_segment_key(segment_key) or ""
                self._backend.apply_events([inflight_event("admit", trace_id, segment_key)])
            else:
                self._inflight[segment_key] += 1

    def complete(self, segment_key: str) -> None:
        """A call for this segment has returned. Floored at 0 so a stray complete cannot
        drive the counter negative."""
        with self._lock:
            if self._backend is not None:
                trace_id = trace_id_from_segment_key(segment_key) or ""
                event = inflight_event("complete", trace_id, segment_key)
                if self._writer is not None:
                    self._writer.submit([event])
                else:
                    self._backend.apply_events([event])
            else:
                self._inflight[segment_key] = max(0, self._inflight[segment_key] - 1)

    def record(self, obs: Observation) -> BoundaryStep:
        """Price the crossing, update every matching budget accumulator, append a
        ``BoundaryStep`` with the run total, and bump the step count.

        This is the LLD's ``Attribute.record()``: the only place spend is written.
        """
        with self._lock:
            rs = self.runs[obs.attr.trace_id]

            cost: Micros = 0
            if obs.node_type == "llm" and obs.usage is not None:
                if self._price is None:
                    raise RuntimeError(
                        "Ledger has no price book; cannot price an llm call (fail closed)"
                    )
                cost = self._price(obs.provider, obs.model, obs.usage)
            elif obs.node_type == "delegate":
                cost = obs.rolled_up_cost_micros  # child run total rolls up into the parent

            rs.steps += 1

            if self._backend is not None:
                # One spent_add per priced crossing; the ack's totals carry the trace total,
                # so no separate precheck is needed for the common case. A zero-cost
                # crossing (tool call) is a step, not spend: nothing is written, and the
                # plane stores no step (control-plane ADR 0009).
                if cost > 0:
                    targets: list[BudgetTarget] = []
                    for b in self._budgets:
                        sk = segment_key(obs.attr, b)
                        if sk is None:
                            continue
                        targets.append(
                            {"budget_id": b.budget_id, "segment_key": sk, "period": b.period}
                        )
                    spend = spent_add_event(obs.attr.trace_id, cost, targets)
                    if self._writer is not None:
                        # Asynchronous: no ack, so the trace total is this process's own
                        # running sum; reads of shared spend go through ``_barrier``.
                        self._writer.submit([spend])
                        rs.cum_spent_cache += cost
                    else:
                        result = self._backend.apply_events([spend])
                        if result.halted:
                            rs.halted = True
                        total_key = (
                            f"{TRACE_TOTAL_BUDGET.budget_id}|trace:{obs.attr.trace_id}|{LIFETIME}"
                        )
                        if total_key in result.totals:
                            rs.cum_spent_cache = result.totals[total_key]
                cum = rs.cum_spent_cache
            else:
                # One event can feed many accumulators (incl. the system run-total) —
                # that is why spend lives in the map, not on the run object. A zero-cost
                # crossing (tool call, delegate with no rollup) must not touch the cost
                # ledger — it is a *step*, not spend.
                if cost > 0:
                    for b in self._budgets:
                        sk = segment_key(obs.attr, b)
                        if sk is None:
                            continue
                        self._write_spent_delta(b.budget_id, sk, b.period, cost)
                cum = self._read_spent(
                    TRACE_TOTAL_BUDGET.budget_id,
                    f"trace:{obs.attr.trace_id}",
                    LIFETIME,
                )
            step = BoundaryStep(
                step=rs.steps,
                ts=obs.ts,
                node_type=obs.node_type,
                boundary_id=obs.boundary_id,
                cum_spent_micros=cum,
                input=obs.input,
                output=obs.output,
                tags={**dict(obs.boundary_tags), **dict(obs.tags)},
                usage=obs.usage,
                signature=obs.signature,
                result_hash=obs.result_hash,
            )
            rs.window.append(step)
            return step

    def mark_halted(self, trace_id: str, reason: str = "") -> None:
        with self._lock:
            rs = self.runs.get(trace_id)
            if rs is not None:
                rs.halted = True
                rs.halt_reason = reason or rs.halt_reason
            if self._backend is not None:
                self._backend.apply_events([halt_event("halt_mark", trace_id, reason=reason)])

    def clear_halt(self, trace_id: str) -> None:
        """Explicit resume of the *same* run — lift the gate. Deliberately separate from
        any automatic path: a halted run never un-halts itself."""
        with self._lock:
            rs = self.runs.get(trace_id)
            if rs is not None:
                rs.halted = False
                rs.halt_reason = None
            if self._backend is not None:
                self._backend.apply_events([halt_event("halt_clear", trace_id)])

    # ---- read side (LedgerView) ------------------------------------------ #

    def cost_micros(self, trace_id: str) -> Micros:
        with self._lock:
            return self._read_spent(TRACE_TOTAL_BUDGET.budget_id, f"trace:{trace_id}", LIFETIME)

    def step_count(self, trace_id: str) -> int:
        with self._lock:
            rs = self.runs.get(trace_id)
            return rs.steps if rs else 0

    def is_halted(self, trace_id: str) -> bool:
        with self._lock:
            rs = self.runs.get(trace_id)
            if rs and rs.halted:
                return True  # fast path: already known locally, no round trip
            if self._backend is not None:
                self._barrier()
                state = self._backend.precheck(PrecheckRequest(trace_id=trace_id, want=["halt"]))
                if state.halted and rs is not None:
                    rs.halted = True
                    rs.halt_reason = state.halt_reason
                return state.halted
            return bool(rs and rs.halted)

    def budget_left(self, budget_id: str, segment_key: str, period: str = "lifetime") -> Micros:
        with self._lock:
            b = self._budget_by_id.get(budget_id)
            if b is None:
                return 0  # unknown budget → no headroom (fail closed)
            if b.limit_micros is None:
                return UNLIMITED_LEFT
            spent = self._read_spent(budget_id, segment_key, period)
            return b.limit_micros - spent

    def inflight(self, segment_key: str) -> int:
        with self._lock:
            if self._backend is not None:
                self._barrier()
                trace_id = trace_id_from_segment_key(segment_key) or ""
                state = self._backend.precheck(
                    PrecheckRequest(
                        trace_id=trace_id, segment_keys=[segment_key], want=["inflight"]
                    )
                )
                return state.inflight.get(segment_key, 0)
            return self._inflight[segment_key]

    def velocity(self, trace_id: str, m: int) -> float:
        with self._lock:
            rs = self.runs.get(trace_id)
            if not rs or len(rs.window) < 2:
                return 0.0
            m = min(m, len(rs.window))
            newest = rs.window[-1].cum_spent_micros
            oldest = rs.window[-m].cum_spent_micros
            return (newest - oldest) / m

    def recent(self, trace_id: str, n: int) -> Sequence[BoundaryStep]:
        with self._lock:
            rs = self.runs.get(trace_id)
            return list(rs.window[-n:]) if rs else []

    def window(self, trace_id: str) -> Sequence[BoundaryStep]:
        with self._lock:
            rs = self.runs.get(trace_id)
            return list(rs.window) if rs else []
