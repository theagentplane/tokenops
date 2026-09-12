"""Ledger — the Attribute module and the read-only LedgerView the policies read from.

State is exactly the LLD's three maps. They are separate on purpose: one boundary
crossing can increment *many* budget accumulators at once, so spend cannot live inside
a single run object.

    runs:     run_id      -> LocalRunState      (per-run ephemeral: steps, window, halted)
    spent:    (budget_id, segment_key, period) -> micros   (one budget bound to a segment)
    inflight: segment_key -> int               (concurrent calls in flight, admit/complete)

Why three maps, not fields on LocalRunState:
  * ``spent`` is budget-scoped — a tenant's monthly cap and this run's cap are two
    accumulators the *same* event feeds. Keying by run would lose that fan-out.
  * ``inflight`` is segment-scoped for concurrency only — it is admit/complete state,
    not spend, so it does not belong on a per-run object either.

Single source of spend truth (Design A): the run total is NOT a separate counter — it
lives in the ``spent`` map under a canonical, always-present run-scoped accumulator
(``RUN_TOTAL_BUDGET``). ``cost_micros`` and each ``BoundaryStep.cum_spent_micros`` are
reads of that one accumulator, so the map is the only place spend is ever written.

Invariant — *every run has a run budget*: structurally guaranteed, because a
``dimension="run"`` budget resolves a fresh ``segment_key`` per run, so one system
budget definition covers every run without you configuring anything.

Concurrency
-----------
One :class:`Ledger` is safe for concurrent threads. Mutations and reads of the in-memory
maps (``runs`` / ``_spent`` / ``_inflight``) are serialized on an internal RLock.

* **Different ``run_id``s** on the same Ledger: safe; spend / steps / halt do not lose
  updates under concurrent ``record`` / ``admit`` / ``mark_halted``.
* **Same ``run_id``**: also safe — calls serialize; halt flags are not torn. Prefer one
  writer per run when possible (typical: per-request Governor), but re-entrancy from
  multiple threads will not corrupt counters.
* **Store-backed Ledger**: spend / inflight / halt go through :class:`~tokenops.control.store.Store`
  (itself thread-safe). Multiple Ledgers / Governors in one process sharing one Store are
  safe for those shared accumulators; each Ledger's step window remains local to that
  Ledger instance.

See ``docs/concurrency.md``.
"""

from __future__ import annotations

import threading
import uuid
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from tokenops.control.core import (
    Attribution,
    BoundaryStep,
    Micros,
    Observation,
)
from tokenops.control.ledger_backend import LedgerBackend, LedgerEvent, PrecheckRequest

if TYPE_CHECKING:
    from tokenops.control.store import Store

#: Resolve a call's price. Injected (the Instrument module owns the price book). Must
#: fail closed: an unknown (provider, model) raises rather than returning 0.
PriceFn = Callable[[str, str, "object"], Micros]

Dimension = Literal["run", "user", "agent", "tenant", "tag"]

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
    dimension: Dimension = "run"
    tag_key: str | None = None
    period: str = "lifetime"


#: The canonical run-total accumulator (Design A). Always present, unlimited, run-scoped —
#: so the run total has exactly one home in ``spent`` and every run is covered by one
#: definition. Never enforced against; ``cost_micros`` and ``cum_spent_micros`` read it.
RUN_TOTAL_BUDGET = Budget(
    budget_id="__run_total__", limit_micros=None, dimension="run", period=LIFETIME
)


def segment_key_for(
    attr: Attribution, dimension: Dimension, tag_key: str | None = None
) -> str | None:
    """Resolve the segment key for a dimension. The shared primitive any policy (budget or
    not — e.g. concurrency_cap) uses to scope itself.

    Returns ``None`` when the attribution does not carry the dimension (e.g. a tenant scope
    on an event with no tenant) — that event simply does not match.
    """
    if dimension == "run":
        return f"run:{attr.run_id}"
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


def _run_id_from_segment_key(segment_key: str) -> str | None:
    """Recover ``run_id`` from a ``run:``-dimension segment key. ``None`` for any other
    dimension (user/agent/tenant/tag) — those don't carry a run_id at all.

    The plane's ``precheck`` only *uses* ``run_id`` to answer ``halt``/``window`` — a
    ``spent`` or ``inflight`` lookup for a non-run segment is valid with an empty
    ``run_id`` (see ``control_plane.store.Store.precheck``), so callers pass ``"" `` when
    this returns ``None`` rather than needing the caller's own run context threaded in.
    """
    prefix = "run:"
    return segment_key[len(prefix) :] if segment_key.startswith(prefix) else None


# --------------------------------------------------------------------------- #
# Backend-mode event builders (see ``ledger_backend.LedgerEvent`` / the control-plane
# ``docs/api-contract.md`` §5-6 for the wire shape and idempotency-key recipe)
# --------------------------------------------------------------------------- #


def _new_idempotency_key() -> str:
    """A fresh, globally-unique key for a one-shot (non-buffered, non-retried) write.

    ``admit``/``complete``/``halt_mark``/``halt_clear`` can be issued for a segment key
    that carries no run_id (e.g. an ``agent``-dimension concurrency cap shared across
    many runs and processes) — the contract's deterministic ``{run_id}:...:{seq}``
    recipe (``docs/api-contract.md`` §6) needs a real, globally-known run_id to stay
    collision-free across processes, which isn't always available here. A random key is
    always correct for a single fire-and-forget write; the deterministic recipe only
    earns its keep once a buffered backend needs a retried flush to regenerate the same
    key (tracked with the ``# TODO(buffering)`` seam in ``ledger_backend.py``).
    """
    return uuid.uuid4().hex


def _inflight_event(
    kind: Literal["admit", "complete"], run_id: str, segment_key: str
) -> LedgerEvent:
    return {
        "kind": kind,
        "idempotency_key": _new_idempotency_key(),
        "run_id": run_id,
        "segment_key": segment_key,
    }


def _halt_event(
    kind: Literal["halt_mark", "halt_clear"],
    run_id: str,
    reason: str = "",
    detector: str = "",
) -> LedgerEvent:
    event: LedgerEvent = {
        "kind": kind,
        "idempotency_key": _new_idempotency_key(),
        "run_id": run_id,
    }
    if reason:
        event["reason"] = reason
    if detector:
        event["detector"] = detector
    return event


def _step_event(obs: Observation, seq: int, cost: Micros) -> LedgerEvent:
    event: LedgerEvent = {
        "kind": "step",
        "idempotency_key": f"{obs.attr.run_id}:{obs.attr.agent}:{seq}:step",
        "ts": obs.ts,
        "run_id": obs.attr.run_id,
        "agent": obs.attr.agent,
        "seq": seq,
        "node_type": obs.node_type,
        "boundary_id": obs.boundary_id,
        "cost_micros": cost,
        "tags": {**dict(obs.boundary_tags), **dict(obs.tags)},
    }
    if obs.usage is not None:
        event["usage"] = {
            "input": obs.usage.input,
            "output": obs.usage.output,
            "cached": obs.usage.cached,
            "reasoning": obs.usage.reasoning,
        }
    if obs.signature is not None:
        event["tool_signature"] = obs.signature
    if obs.result_hash is not None:
        event["result_hash"] = obs.result_hash
    return event


def _spent_add_event(
    run_id: str, agent: str, seq: int, delta: Micros, targets: list[dict[str, str]]
) -> LedgerEvent:
    return {
        "kind": "spent_add",
        "idempotency_key": f"{run_id}:{agent}:{seq}:spent_add",
        "run_id": run_id,
        "delta_micros": delta,
        "targets": targets,
    }


# =========================================================================== #
# Per-run ephemeral state                                                      #
# =========================================================================== #


@dataclass
class LocalRunState:
    """Ephemeral per-process, per-run cache (Tier 1). The dict key in ``Ledger.runs`` is
    the run_id — there is deliberately no run_id field here (the index is not a field).

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
    """Attribute + LedgerView. Per-process run state (window, local step count); spend,
    inflight, and halt may be backed by :class:`Store` (local SQLite) or a
    :class:`~tokenops.control.ledger_backend.LedgerBackend` (the remote control plane) for
    cross-process / cross-agent consistency. At most one of ``store``/``backend`` may be
    given; neither means fully in-memory (single-process only, tests).

    ``backend`` mode is the target of the remote-only rewrite (tokenops#118): every write
    goes through ``apply_events`` (one batch per crossing) and every spend/inflight/halt
    read goes through ``read_state`` (``precheck``). There is no per-call batching across
    detectors yet — each read is its own round trip — so a call with several ``global``-
    scope policies costs more than one ``precheck``; that optimization (and buffering the
    write side) are tracked follow-ups, not required for correctness.

    Thread-safe for concurrent use from multiple threads (see module docstring).
    """

    def __init__(
        self,
        *,
        budgets: Sequence[Budget] = (),
        price: PriceFn | None = None,
        store: Store | None = None,
        backend: LedgerBackend | None = None,
    ) -> None:
        if store is not None and backend is not None:
            raise ValueError("Ledger takes at most one of store= / backend=, not both")
        self._lock = threading.RLock()
        self._store = store
        self._backend = backend
        self.runs: dict[str, LocalRunState] = {}
        self._spent: dict[tuple[str, str, str], Micros] = defaultdict(int)
        self._inflight: dict[str, int] = defaultdict(int)
        self._budgets: list[Budget] = [RUN_TOTAL_BUDGET, *budgets]
        self._budget_by_id: dict[str, Budget] = {b.budget_id: b for b in self._budgets}
        self._price = price

    def _spent_key(self, budget_id: str, segment_key: str, period: str) -> tuple[str, str, str]:
        return (budget_id, segment_key, period)

    def _read_spent(self, budget_id: str, segment_key: str, period: str) -> Micros:
        if self._backend is not None:
            state = self._backend.read_state(
                PrecheckRequest(
                    run_id=_run_id_from_segment_key(segment_key) or "",
                    budgets=[
                        {"budget_id": budget_id, "segment_key": segment_key, "period": period}
                    ],
                    want=["spent"],
                )
            )
            return state.spent.get(f"{budget_id}|{segment_key}|{period}", 0)
        if self._store is not None:
            return self._store.ledger_get_spent(budget_id, segment_key, period)
        return self._spent[self._spent_key(budget_id, segment_key, period)]

    def _write_spent_delta(
        self,
        budget_id: str,
        segment_key: str,
        period: str,
        delta: Micros,
    ) -> Micros:
        # Backend mode batches spent_add into record()'s single apply_events call
        # (it needs to share an idempotency key/seq with that crossing's step event),
        # so it never reaches this in-memory/Store fallback path.
        if self._store is not None:
            return self._store.ledger_add_spent(budget_id, segment_key, period, delta)
        key = self._spent_key(budget_id, segment_key, period)
        self._spent[key] += delta
        return self._spent[key]

    # ---- write side (Attribute) ------------------------------------------ #

    def open_run(self, run_id: str, parent_run: str | None = None) -> None:
        with self._lock:
            self.runs[run_id] = LocalRunState(parent_run=parent_run)

    def close_run(self, run_id: str) -> None:
        """Drop the per-process :class:`LocalRunState` for a finished run. Idempotent.

        ``tokenops_run`` calls this on scope exit for the run it opened, so a
        long-lived / shared-governor process does not accumulate ``LocalRunState``
        entries (each holds a full ``window`` of ``BoundaryStep``s).
        """
        with self._lock:
            self.runs.pop(run_id, None)

    def admit(self, segment_key: str) -> None:
        """A call for this segment has started (concurrency)."""
        with self._lock:
            if self._backend is not None:
                run_id = _run_id_from_segment_key(segment_key) or ""
                self._backend.apply_events([_inflight_event("admit", run_id, segment_key)])
            elif self._store is not None:
                self._store.ledger_admit(segment_key)
            else:
                self._inflight[segment_key] += 1

    def complete(self, segment_key: str) -> None:
        """A call for this segment has returned. Floored at 0 so a stray complete cannot
        drive the counter negative."""
        with self._lock:
            if self._backend is not None:
                run_id = _run_id_from_segment_key(segment_key) or ""
                self._backend.apply_events([_inflight_event("complete", run_id, segment_key)])
            elif self._store is not None:
                self._store.ledger_complete(segment_key)
            else:
                self._inflight[segment_key] = max(0, self._inflight[segment_key] - 1)

    def record(self, obs: Observation) -> BoundaryStep:
        """Price the crossing, update every matching budget accumulator, append a
        ``BoundaryStep`` with the run total, and bump the step count.

        This is the LLD's ``Attribute.record()``: the only place spend is written.
        """
        with self._lock:
            rs = self.runs[obs.attr.run_id]

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
                # One apply_events batch for both the step and the spend, so they share
                # an idempotency seq and the ack's totals cover the run-total in one
                # round trip (no separate read_state needed for the common case).
                events: list[LedgerEvent] = [_step_event(obs, rs.steps, cost)]
                if cost > 0:
                    targets = []
                    for b in self._budgets:
                        sk = segment_key(obs.attr, b)
                        if sk is None:
                            continue
                        targets.append(
                            {"budget_id": b.budget_id, "segment_key": sk, "period": b.period}
                        )
                    events.append(
                        _spent_add_event(obs.attr.run_id, obs.attr.agent, rs.steps, cost, targets)
                    )
                result = self._backend.apply_events(events)
                if result.halted:
                    rs.halted = True
                run_total_key = f"{RUN_TOTAL_BUDGET.budget_id}|run:{obs.attr.run_id}|{LIFETIME}"
                if run_total_key in result.totals:
                    rs.cum_spent_cache = result.totals[run_total_key]
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
                    RUN_TOTAL_BUDGET.budget_id,
                    f"run:{obs.attr.run_id}",
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

    def mark_halted(self, run_id: str, reason: str = "") -> None:
        with self._lock:
            rs = self.runs.get(run_id)
            if rs is None:
                rs = self.runs[run_id] = LocalRunState()
            rs.halted = True
            rs.halt_reason = reason or rs.halt_reason
            if self._backend is not None:
                self._backend.apply_events([_halt_event("halt_mark", run_id, reason=reason)])
            elif self._store is not None:
                self._store.ledger_mark_halted(run_id, reason)

    def clear_halt(self, run_id: str) -> None:
        """Explicit resume of the *same* run — lift the gate. Deliberately separate from
        any automatic path: a halted run never un-halts itself."""
        with self._lock:
            rs = self.runs.get(run_id)
            if rs is not None:
                rs.halted = False
                rs.halt_reason = None
            if self._backend is not None:
                self._backend.apply_events([_halt_event("halt_clear", run_id)])
            elif self._store is not None:
                self._store.ledger_clear_halt(run_id)

    # ---- read side (LedgerView) ------------------------------------------ #

    def cost_micros(self, run_id: str) -> Micros:
        with self._lock:
            return self._read_spent(RUN_TOTAL_BUDGET.budget_id, f"run:{run_id}", LIFETIME)

    def step_count(self, run_id: str) -> int:
        with self._lock:
            rs = self.runs.get(run_id)
            return rs.steps if rs else 0

    def is_halted(self, run_id: str) -> bool:
        with self._lock:
            rs = self.runs.get(run_id)
            if rs and rs.halted:
                return True  # fast path: already known locally, no round trip
            if self._backend is not None:
                state = self._backend.read_state(PrecheckRequest(run_id=run_id, want=["halt"]))
                if state.halted:
                    if rs is None:
                        rs = self.runs[run_id] = LocalRunState()
                    rs.halted = True
                    rs.halt_reason = state.halt_reason
                return state.halted
            if self._store is not None and self._store.ledger_is_halted(run_id):
                return True
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
                run_id = _run_id_from_segment_key(segment_key) or ""
                state = self._backend.read_state(
                    PrecheckRequest(run_id=run_id, segment_keys=[segment_key], want=["inflight"])
                )
                return state.inflight.get(segment_key, 0)
            if self._store is not None:
                return self._store.ledger_inflight(segment_key)
            return self._inflight[segment_key]

    def velocity(self, run_id: str, m: int) -> float:
        with self._lock:
            rs = self.runs.get(run_id)
            if not rs or len(rs.window) < 2:
                return 0.0
            m = min(m, len(rs.window))
            newest = rs.window[-1].cum_spent_micros
            oldest = rs.window[-m].cum_spent_micros
            return (newest - oldest) / m

    def recent(self, run_id: str, n: int) -> Sequence[BoundaryStep]:
        with self._lock:
            rs = self.runs.get(run_id)
            return list(rs.window[-n:]) if rs else []

    def window(self, run_id: str) -> Sequence[BoundaryStep]:
        with self._lock:
            rs = self.runs.get(run_id)
            return list(rs.window) if rs else []
