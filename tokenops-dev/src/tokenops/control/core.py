"""Control-plane core vocabulary — LLD-faithful, single source of truth.

This module is the shared language the ledger, the policy templates, and the
harness all speak. It is deliberately small: the policies LLD reads exactly these
fields off a ``BoundaryStep`` and a ``CallRequest`` — nothing more.

Layer split (mirrors the LLD's Instrument / Attribute table):

    Instrument / IN   emits a lean ``Observation`` at each boundary exit
    Attribute         prices it, updates ``spent``, appends a ``BoundaryStep``
    Enforce           reads the ``LedgerView`` (BoundaryStep window + accumulators)

Design rules:
* Cost is micro-USD ``int`` (``Micros``) everywhere — cross-provider, no float drift.
* Telemetry/decision records are ``frozen, kw_only`` dataclasses — immutable, hashable,
  safe to share across detectors, and extensible without the argument-order trap.
* ``Detector`` / ``Policy`` are ABCs with no-op defaults — override one hook.
* Fail closed — an unknown price or unhandled action blocks; it never silently allows.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Mapping, Protocol, Sequence, runtime_checkable

__all__ = [
    "Micros",
    "NodeType",
    "Usage",
    "Attribution",
    "Observation",
    "BoundaryStep",
    "CallRequest",
    "Severity",
    "Signal",
    "ActionKind",
    "Action",
    "Halt",
    "Detector",
    "Policy",
    "LedgerView",
    # scaffold aliases
    "Attr",
    "Act",
]

#: Cost in micro-US-dollars. ``$1.00 == 1_000_000``. Integer math avoids float drift.
Micros = int

#: Chronicle boundary_kind, LLD vocabulary. Not "model"/"delegation" — these literals.
NodeType = Literal["llm", "tool", "delegate"]


# =========================================================================== #
# Value objects                                                               #
# =========================================================================== #

@dataclass(frozen=True, kw_only=True)
class Usage:
    """Provider-reported token *totals* for one call — never the streamed text.

    ``cached`` and ``reasoning`` mirror the hidden, costly categories providers report
    (OpenAI ``*_tokens_details``; Anthropic ``cache_read_input_tokens``). Track them or
    the spend most likely to surprise you stays invisible.
    """

    input: int = 0
    output: int = 0
    cached: int = 0
    reasoning: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input=self.input + other.input,
            output=self.output + other.output,
            cached=self.cached + other.cached,
            reasoning=self.reasoning + other.reasoning,
        )


@dataclass(frozen=True, kw_only=True)
class Attribution:
    """Whose spend an event represents — the dimensions a budget/segment can match.

    ``run_id`` ties every crossing into one run. ``parent_run`` links a delegated child
    back to its caller so cost lineage survives an A2A hop. ``tags`` carries arbitrary
    segment matchers (corpus_profile, environment, …).
    """

    user: str
    agent: str
    run_id: str
    tenant: str | None = None
    parent_run: str | None = None
    tags: Mapping[str, str] = field(default_factory=dict)


# =========================================================================== #
# Telemetry: Observation (IN) -> BoundaryStep (stored)                         #
# =========================================================================== #

@dataclass(frozen=True, kw_only=True)
class Observation:
    """Lean telemetry the Instrument/IN layer emits at a boundary exit.

    No ``cost_micros`` and no ``cum_spent`` — those are Attribute's job. ``provider`` /
    ``model`` are present only for ``llm`` (so Attribute can price). One record for all
    three node types, discriminated by ``node_type`` — the LLD reads fields off this, not
    off a class hierarchy.
    """

    attr: Attribution
    node_type: NodeType
    boundary_id: str
    ts: float
    input: Mapping[str, object] = field(default_factory=dict)
    output: Mapping[str, object] = field(default_factory=dict)
    tags: Mapping[str, str] = field(default_factory=dict)
    # llm only:
    provider: str = ""
    model: str = ""
    usage: Usage | None = None
    # tool only:
    signature: str | None = None
    result_hash: str | None = None
    # delegate only: child run total reported up the A2A hop
    rolled_up_cost_micros: Micros = 0


@dataclass(frozen=True, kw_only=True)
class BoundaryStep:
    """One completed boundary crossing, as stored in the run ``window``.

    Built by Attribute *after* pricing — which is why ``cum_spent_micros`` (the run total
    AFTER this step) lives here and not on the raw :class:`Observation`. This is the lean
    projection detectors read via ``recent`` / ``window``.
    """

    step: int
    ts: float
    node_type: NodeType
    boundary_id: str
    cum_spent_micros: Micros
    input: Mapping[str, object] = field(default_factory=dict)
    output: Mapping[str, object] = field(default_factory=dict)
    tags: Mapping[str, str] = field(default_factory=dict)
    usage: Usage | None = None
    signature: str | None = None
    result_hash: str | None = None


@dataclass(frozen=True, kw_only=True)
class CallRequest:
    """A model call about to be dispatched, inspected by ``Detector.pre_call`` *before*
    any tokens are spent (budget gate, worst-case ceiling, oversized-input guard)."""

    attr: Attribution
    provider: str
    model: str
    estimated_input_tokens: int = 0
    max_output_tokens: int | None = None


# =========================================================================== #
# Decisions: Signal (detect) -> Action (decide) -> apply (OUT)                 #
# =========================================================================== #

class Severity(str, Enum):
    """How strongly a detector reacts. ``WARN`` invites a corrective response;
    ``TRIP`` calls for a preventive one."""

    OK = "ok"
    WARN = "warn"
    TRIP = "trip"


@dataclass(frozen=True, kw_only=True)
class Signal:
    """A detection. Analysis *recommends*; Enforcement *decides*. ``evidence`` carries the
    numbers behind the call for explainable decisions and audit trails."""

    detector: str
    severity: Severity
    run_id: str
    reason: str = ""
    evidence: Mapping[str, object] = field(default_factory=dict)


class ActionKind(str, Enum):
    """The OUT controls from the LLD. The breaker owns HALT and CANCEL; everything else
    heals or bounds. Add a kind here and handle it in the OUT connector — the connector
    signature never changes (open/closed)."""

    ALLOW = "allow"
    HALT = "halt"
    CANCEL = "cancel"
    REJECT = "reject"
    QUEUE = "queue"
    MUTATE = "mutate"
    INJECT = "inject"
    RETRY = "retry"


@dataclass(frozen=True, kw_only=True)
class Action:
    """The decision applied to a run. One flat dataclass for every kind so the OUT
    connector stays a single polymorphic ``apply(action)``; unused payloads are ``None``."""

    kind: ActionKind
    run_id: str
    reason: str = ""
    # MUTATE payloads
    downgrade_to: str | None = None
    max_output_tokens: int | None = None
    # INJECT payload
    inject_message: str | None = None
    # REJECT / QUEUE payload
    retry_after_s: float | None = None


class Halt(BaseException):
    """Raised through the data plane's existing callback to abort a run.

    Extends ``BaseException`` (not ``Exception``) so a framework's broad
    ``except Exception`` for flaky APIs cannot swallow the breaker. Carries the deciding
    :class:`Action` so the boundary returns a structured "halted, here is the partial
    cost" response instead of a generic 500.
    """

    def __init__(self, action: Action) -> None:
        super().__init__(action.reason)
        self.action = action


# =========================================================================== #
# Read-only ledger view (Attribute -> Enforce)                                 #
# =========================================================================== #

@runtime_checkable
class LedgerView(Protocol):
    """Read-only run state Attribute hands to Enforce. Detectors read, never write.

    Complexity contract — keep detector hot paths cheap:
      * ``cost_micros`` / ``step_count`` / ``budget_left`` / ``inflight`` are **O(1)**.
      * ``recent`` / ``velocity`` are **O(window)** — bounded tail.
      * ``window`` is **O(N)** — escape hatch; do not call on every ``observe``.
    """

    def cost_micros(self, run_id: str) -> Micros: ...

    def step_count(self, run_id: str) -> int: ...

    def is_halted(self, run_id: str) -> bool: ...

    def budget_left(self, budget_id: str, segment_key: str, period: str) -> Micros: ...

    def inflight(self, segment_key: str) -> int: ...

    def velocity(self, run_id: str, m: int) -> float: ...

    def recent(self, run_id: str, n: int) -> Sequence[BoundaryStep]: ...

    def window(self, run_id: str) -> Sequence[BoundaryStep]: ...


# =========================================================================== #
# Extension points: Detector, Policy (ABCs with no-op defaults)                #
# =========================================================================== #

class Detector(ABC):
    """A breaker / signal source. Each hook is ``(input, read-only view) -> Signal | None``.

    Override only the hooks your signal needs; the rest are no-ops. Detectors read ledger
    state but never write it — that keeps them trivially unit-testable against a mocked view.
    """

    name: str = "detector"

    def pre_call(self, request: CallRequest, view: LedgerView) -> Signal | None:
        """Inspect a call before dispatch (budget gate, worst case, oversized input)."""
        return None

    def observe(self, attr: Attribution, step: BoundaryStep, view: LedgerView) -> Signal | None:
        """Inspect a completed boundary step (loops, velocity, budget, runaway).

        ``attr`` is the run's attribution, passed by reference by the harness — it is the
        same object for every step in the run, so detectors get run_id and every segment
        dimension *without* it being duplicated onto each entry of the unbounded window.
        """
        return None

    def tick(self, now: float, view: LedgerView) -> Signal | None:
        """Inspect on a clock, independent of events (timeouts, stalls)."""
        return None

    def reset(self, run_id: str) -> None:
        """Drop any per-run state held for ``run_id``."""
        return None


class Policy(ABC):
    """Maps a :class:`Signal` to an :class:`Action`.

    Preventive policies return HALT/CANCEL; corrective ones MUTATE/INJECT/RETRY/QUEUE.
    Policies compose — the harness combines their actions (HALT precedence, worst-first).
    """

    name: str = "policy"

    @abstractmethod
    def decide(self, signal: Signal, view: LedgerView) -> Action: ...


# =========================================================================== #
# Scaffold aliases — control/__init__.py was written against short names       #
# =========================================================================== #

Attr = Attribution
Act = ActionKind
