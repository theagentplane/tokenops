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
  (:class:`~tokenops.repositories.ControlPlaneClient`). Multiple Ledgers / Governors sharing one
  plane share those accumulators; each Ledger's step window stays local to that Ledger
  instance (the plane stores no step window, control-plane ADR 0009).

See ``docs/concurrency.md``.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from tokenops.control.core import (
    Attribution,
    BoundaryStep,
    Micros,
    Observation,
)
from tokenops.repositories import (
    BudgetTarget,
    ControlPlaneClient,
    LedgerEvent,
    PrecheckRequest,
)

#: Resolve a call's price. Injected (the Instrument module owns the price book). Must
#: fail closed: an unknown (provider, model) raises rather than returning 0.
PriceFn = Callable[[str, str, "object"], Micros]

Dimension = Literal["trace", "user", "agent", "tenant", "tag"]

#: Period label for the run-total accumulator and v1 budgets (whole-run / lifetime).
LIFETIME = "lifetime"

#: A budget_left answer for an unlimited (``limit_micros is None``) accumulator. Large
#: enough that no worst-case projection treats it as exhausted; never enforced against.
UNLIMITED_LEFT: Micros = 1 << 62


# =========================================================================== #
# Budget — a limit bound to a segment matcher (config template instantiates these)
# =========================================================================== #


@dataclass(frozen=True, kw_only=True)
class Budget:
    """A spend limit attached to one segment dimension.

    ``limit_micros = None`` means *unlimited* — a pure accumulator that totals spend but
    never trips. The system run-total budget is the canonical example: it exists so the
    run total has one home in the ``spent`` map, not to cap anything.

    ``dimension`` picks which Attribution field forms the segment key; ``tag_key`` names
    the tag when ``dimension == "tag"``. ``period`` labels the accumulator bucket
    ("lifetime" for v1; monthly/daily bucketing is a future refinement of the key).
    """

    budget_id: str
    limit_micros: Micros | None
    dimension: Dimension = "trace"
    tag_key: str | None = None
    period: str = "lifetime"


#: The canonical run-total accumulator (Design A). Always present, unlimited, run-scoped —
#: so the run total has exactly one home in ``spent`` and every run is covered by one
#: definition. Never enforced against; ``cost_micros`` and ``cum_spent_micros`` read it.
TRACE_TOTAL_BUDGET = Budget(
    budget_id="__trace_total__", limit_micros=None, dimension="trace", period=LIFETIME
)


def segment_key_for(
    attr: Attribution, dimension: Dimension, tag_key: str | None = None
) -> str | None:
    """Resolve the segment key for a dimension. The shared primitive any policy (budget or
    not — e.g. concurrency_cap) uses to scope itself.

    Returns ``None`` when the attribution does not carry the dimension (e.g. a tenant scope
    on an event with no tenant) — that event simply does not match.
    """
    if dimension == "trace":
        return f"trace:{attr.trace_id}"
    if dimension == "user":
        return f"user:{attr.user}"
    if dimension == "agent":
        return f"agent:{attr.agent}"
    if dimension == "tenant":
        return f"tenant:{attr.tenant}" if attr.tenant else None
    if dimension == "tag":
        if tag_key and tag_key in attr.tags:
            return f"tag:{tag_key}={attr.tags[tag_key]}"
        return None
    return None


def segment_key(attr: Attribution, budget: Budget) -> str | None:
    """Resolve the segment key this *budget* matches — thin wrapper over ``segment_key_for``."""
    return segment_key_for(attr, budget.dimension, budget.tag_key)


def _trace_id_from_segment_key(segment_key: str) -> str | None:
    """Recover ``trace_id`` from a ``trace:``-dimension segment key. ``None`` for any other
    dimension (user/agent/tenant/tag) — those don't carry a trace_id at all.

    The plane's ``precheck`` only *uses* ``trace_id`` to answer ``halt`` — a ``spent`` or
    ``inflight`` lookup for a non-trace segment is valid with an empty ``trace_id``, so
    callers pass ``""`` when this returns ``None``.
    """
    prefix = "trace:"
    return segment_key[len(prefix) :] if segment_key.startswith(prefix) else None


# --------------------------------------------------------------------------- #
# Event builders (control plane 1.0 wire shape; no step events, no idempotency key —
# control-plane ADR 0007 / 0009)
# --------------------------------------------------------------------------- #


def _inflight_event(
    kind: Literal["admit", "complete"], trace_id: str, segment_key: str
) -> LedgerEvent:
    return {"kind": kind, "trace_id": trace_id, "segment_key": segment_key}


def _halt_event(
    kind: Literal["halt_mark", "halt_clear"], trace_id: str, reason: str = ""
) -> LedgerEvent:
    event: LedgerEvent = {"kind": kind, "trace_id": trace_id}
    if reason:
        event["reason"] = reason
    return event


def _spent_add_event(trace_id: str, delta: Micros, targets: list[BudgetTarget]) -> LedgerEvent:
    return {
        "kind": "spent_add",
        "trace_id": trace_id,
        "delta_micros": delta,
        "targets": targets,
    }


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
    (:class:`~tokenops.repositories.ControlPlaneClient`) for cross-process / cross-agent
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
        backend: ControlPlaneClient | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._backend = backend
        self.runs: dict[str, LocalRunState] = {}
        self._spent: dict[tuple[str, str, str], Micros] = defaultdict(int)
        self._inflight: dict[str, int] = defaultdict(int)
        self._budgets: list[Budget] = [TRACE_TOTAL_BUDGET, *budgets]
        self._budget_by_id: dict[str, Budget] = {b.budget_id: b for b in self._budgets}
        self._price = price

    def _spent_key(self, budget_id: str, segment_key: str, period: str) -> tuple[str, str, str]:
        return (budget_id, segment_key, period)

    def _read_spent(self, budget_id: str, segment_key: str, period: str) -> Micros:
        if self._backend is not None:
            state = self._backend.precheck(
                PrecheckRequest(
                    trace_id=_trace_id_from_segment_key(segment_key) or "",
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
                trace_id = _trace_id_from_segment_key(segment_key) or ""
                self._backend.apply_events([_inflight_event("admit", trace_id, segment_key)])
            else:
                self._inflight[segment_key] += 1

    def complete(self, segment_key: str) -> None:
        """A call for this segment has returned. Floored at 0 so a stray complete cannot
        drive the counter negative."""
        with self._lock:
            if self._backend is not None:
                trace_id = _trace_id_from_segment_key(segment_key) or ""
                self._backend.apply_events([_inflight_event("complete", trace_id, segment_key)])
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
                    result = self._backend.apply_events(
                        [_spent_add_event(obs.attr.trace_id, cost, targets)]
                    )
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
            if rs is None:
                rs = self.runs[trace_id] = LocalRunState()
            rs.halted = True
            rs.halt_reason = reason or rs.halt_reason
            if self._backend is not None:
                self._backend.apply_events([_halt_event("halt_mark", trace_id, reason=reason)])

    def clear_halt(self, trace_id: str) -> None:
        """Explicit resume of the *same* run — lift the gate. Deliberately separate from
        any automatic path: a halted run never un-halts itself."""
        with self._lock:
            rs = self.runs.get(trace_id)
            if rs is not None:
                rs.halted = False
                rs.halt_reason = None
            if self._backend is not None:
                self._backend.apply_events([_halt_event("halt_clear", trace_id)])

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
                state = self._backend.precheck(PrecheckRequest(trace_id=trace_id, want=["halt"]))
                if state.halted:
                    if rs is None:
                        rs = self.runs[trace_id] = LocalRunState()
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
                trace_id = _trace_id_from_segment_key(segment_key) or ""
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
