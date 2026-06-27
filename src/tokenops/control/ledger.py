"""Ledger — the Attribute module and the read-only LedgerView the policies read from.

State is exactly the LLD's three maps. They are separate on purpose: one boundary
crossing can increment *many* budget accumulators at once, so spend cannot live inside
a single run object.

    runs:     run_id      -> RunState          (per-run ephemeral: steps, window, halted)
    spent:    (budget_id, segment_key, period) -> micros   (one budget bound to a segment)
    inflight: segment_key -> int               (concurrent calls in flight, admit/complete)

Why three maps, not fields on RunState:
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
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Literal, Sequence

from tokenops.control.core import (
    Attribution,
    BoundaryStep,
    Micros,
    Observation,
)

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
RUN_TOTAL_BUDGET = Budget(budget_id="__run_total__", limit_micros=None, dimension="run", period=LIFETIME)


def segment_key_for(attr: Attribution, dimension: Dimension, tag_key: str | None = None) -> str | None:
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


# =========================================================================== #
# Per-run ephemeral state                                                      #
# =========================================================================== #

@dataclass
class RunState:
    """Ephemeral per-run state. The dict key in ``Ledger.runs`` is the run_id — there is
    deliberately no run_id field here (the index is not a field)."""

    steps: int = 0
    window: list[BoundaryStep] = field(default_factory=list)
    halted: bool = False
    halt_reason: str | None = None
    parent_run: str | None = None


# =========================================================================== #
# The ledger (Attribute + LedgerView in one in-memory implementation)          #
# =========================================================================== #

class Ledger:
    """In-memory Attribute. Single-process backend for v1; the same shape backs a shared
    store in distributed A2A (only the dict gets swapped for Redis/etc.)."""

    def __init__(self, *, budgets: Sequence[Budget] = (), price: PriceFn | None = None) -> None:
        self.runs: dict[str, RunState] = {}
        # Internal accumulators (underscored so the public ``inflight()`` read method from
        # LedgerView does not collide with the dict). Conceptually these are the LLD's
        # ``spent`` and ``inflight`` maps.
        self._spent: dict[tuple[str, str, str], Micros] = defaultdict(int)
        self._inflight: dict[str, int] = defaultdict(int)
        # The system run-total accumulator is always first, so every run's total has one
        # home in ``spent`` regardless of which (if any) budgets the caller configured.
        self._budgets: list[Budget] = [RUN_TOTAL_BUDGET, *budgets]
        self._budget_by_id: dict[str, Budget] = {b.budget_id: b for b in self._budgets}
        self._price = price

    # ---- write side (Attribute) ------------------------------------------ #

    def open_run(self, run_id: str, parent_run: str | None = None) -> None:
        self.runs[run_id] = RunState(parent_run=parent_run)

    def admit(self, segment_key: str) -> None:
        """A call for this segment has started (concurrency)."""
        self._inflight[segment_key] += 1

    def complete(self, segment_key: str) -> None:
        """A call for this segment has returned. Floored at 0 so a stray complete cannot
        drive the counter negative."""
        self._inflight[segment_key] = max(0, self._inflight[segment_key] - 1)

    def record(self, obs: Observation) -> BoundaryStep:
        """Price the crossing, update every matching budget accumulator, append a
        ``BoundaryStep`` with the run total, and bump the step count.

        This is the LLD's ``Attribute.record()``: the only place spend is written.
        """
        rs = self.runs[obs.attr.run_id]

        cost: Micros = 0
        if obs.node_type == "llm" and obs.usage is not None:
            if self._price is None:
                raise RuntimeError("Ledger has no price book; cannot price an llm call (fail closed)")
            cost = self._price(obs.provider, obs.model, obs.usage)
        elif obs.node_type == "delegate":
            cost = obs.rolled_up_cost_micros  # child run total rolls up into the parent

        # One event can feed many accumulators (incl. the system run-total) — that is why
        # spend lives in the map, not on the run object.
        for b in self._budgets:
            sk = segment_key(obs.attr, b)
            if sk is None:
                continue
            self._spent[(b.budget_id, sk, b.period)] += cost

        rs.steps += 1
        # cum_spent is READ back from the canonical run accumulator — single source of truth.
        cum = self._spent[(RUN_TOTAL_BUDGET.budget_id, f"run:{obs.attr.run_id}", LIFETIME)]
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
        rs = self.runs.get(run_id)
        if rs is None:
            rs = self.runs[run_id] = RunState()
        rs.halted = True
        rs.halt_reason = reason or rs.halt_reason

    def clear_halt(self, run_id: str) -> None:
        """Explicit resume of the *same* run — lift the gate. Deliberately separate from
        any automatic path: a halted run never un-halts itself."""
        rs = self.runs.get(run_id)
        if rs is not None:
            rs.halted = False
            rs.halt_reason = None

    # ---- read side (LedgerView) ------------------------------------------ #

    def cost_micros(self, run_id: str) -> Micros:
        # Read of the canonical run accumulator — the single source of spend truth.
        return self._spent[(RUN_TOTAL_BUDGET.budget_id, f"run:{run_id}", LIFETIME)]

    def step_count(self, run_id: str) -> int:
        rs = self.runs.get(run_id)
        return rs.steps if rs else 0

    def is_halted(self, run_id: str) -> bool:
        rs = self.runs.get(run_id)
        return bool(rs and rs.halted)

    def budget_left(self, budget_id: str, segment_key: str, period: str = "lifetime") -> Micros:
        b = self._budget_by_id.get(budget_id)
        if b is None:
            return 0  # unknown budget → no headroom (fail closed)
        if b.limit_micros is None:
            return UNLIMITED_LEFT  # pure accumulator (e.g. run-total) — never trips
        return b.limit_micros - self._spent[(budget_id, segment_key, period)]

    def inflight(self, segment_key: str) -> int:
        return self._inflight[segment_key]

    def velocity(self, run_id: str, m: int) -> float:
        rs = self.runs.get(run_id)
        if not rs or len(rs.window) < 2:
            return 0.0
        m = min(m, len(rs.window))
        newest = rs.window[-1].cum_spent_micros
        oldest = rs.window[-m].cum_spent_micros
        return (newest - oldest) / m

    def recent(self, run_id: str, n: int) -> Sequence[BoundaryStep]:
        rs = self.runs.get(run_id)
        return rs.window[-n:] if rs else []

    def window(self, run_id: str) -> Sequence[BoundaryStep]:
        rs = self.runs.get(run_id)
        return list(rs.window) if rs else []
