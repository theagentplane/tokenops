"""Control-plane interface contracts for TokenOps.

TokenOps governs token spend for AI agents. The data plane (your agents) stays
vanilla; the control plane is **two connectors** around **three modules**:

    data plane                CONTROL PLANE                        data plane
    ──────────       ┌────────────┬───────────┬──────────┐      ──────────
    agent  ──IN──▶   │ Instrument │ Attribute │  Enforce  │ ─OUT─▶  agent
   (telemetry)       │  measure   │   tag &   │  watch &  │       (controls)
                     │  & price   │  remember │    act    │
                     │  → Event   │ → Ledger  │ → Action  │
                     └────────────┴───────────┴──────────┘

Two questions the control plane answers:

1. *What information do I have?* — ``Event`` (Instrument + Attribute) and ``Signal`` (Enforce).
2. *What can I do about it?* — ``Action`` (Enforce): preventive (hard stop) or
   corrective (optimise at runtime / in the background).

Three moments a call can be governed — mutually exclusive, collectively exhaustive
over time: ``pre_call`` (before), ``observe`` (after each event), ``tick`` (on a clock).

Design rules
------------
* Enforce on **cost** (micro-USD ``int``), never raw tokens — cross-provider safe,
  no floating-point drift.
* Data contracts are **frozen, keyword-only dataclasses**: immutable, hashable, safely
  extensible (``kw_only`` removes the default-argument ordering trap when subclassing),
  and trivially mocked.
* Module and connector boundaries are **Protocols** — structural typing means stubs
  and mocks need no inheritance.
* Extension points (``Detector``, ``Policy``) are **ABCs with no-op defaults** so
  authors override only what they need.
* **Fail closed**: an unknown model, price, or condition blocks or flags — it never
  silently allows.
* Every handoff is a dataclass, so any module can be built and tested against a
  mocked neighbour.

Extending
---------
* New telemetry kind  → subclass :class:`Event` (set ``kind``); the pipeline is unchanged.
* New runaway signal  → subclass :class:`Detector`, override one hook, ``register`` it.
* New response        → add an :class:`ActionKind` and handle it in your
  :class:`AgentControls.apply`; subclass :class:`Policy` to emit it.

Integrating
-----------
* **Greenfield** — ``with cp.run(...) as r: client = cp.wrap(model_client); r.record_tool(...)``.
* **Brownfield** — pass ``cp.on_step()`` into your agent's existing step callback and
  wrap its model entry point; no change to agent logic.

See ``integration_example.py`` for runnable reference adapters for both.

Status: draft (0.x). Contracts may change until a 1.0 tag. Requires Python 3.10+.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, ClassVar, Mapping, Protocol, Sequence, TypeVar, runtime_checkable

__all__ = [
    "Micros",
    # data: telemetry
    "Usage",
    "Attribution",
    "EventKind",
    "Event",
    "ModelCall",
    "ToolCall",
    "Delegation",
    "CallRequest",
    # data: decisions
    "Severity",
    "Signal",
    "ActionKind",
    "Action",
    "Halt",
    # modules
    "Instrument",
    "Attribute",
    "LedgerView",
    # extension points (Module 3: Enforce)
    "Detector",
    "Policy",
    # connectors + facade
    "TelemetrySource",
    "AgentControls",
    "ControlPlane",
    "RunContext",
]

#: Cost in micro-US-dollars. ``$1.00 == 1_000_000``. Integer math avoids float drift.
Micros = int

#: Preserves a wrapped client's exact type through ``ControlPlane.wrap`` (keeps IDE autocomplete).
T = TypeVar("T")

#: A framework step callback. It receives the framework's own step object (not a contract
#: ``Event``), maps it to an ``Event``, and emits it. This is what ``ControlPlane.on_step`` returns.
StepCallback = Callable[[object], None]


# =========================================================================== #
# 1. VALUE OBJECTS                                                            #
# =========================================================================== #
# Small, shared building blocks. ``kw_only=True`` makes construction explicit and
# keeps these safe to extend later without breaking call sites.

@dataclass(frozen=True, kw_only=True)
class Usage:
    """Token counts from the provider's usage *totals* — never the streamed text.

    ``cached`` and ``reasoning`` mirror the costly hidden categories the providers
    report (OpenAI ``prompt_tokens_details.cached_tokens`` /
    ``completion_tokens_details.reasoning_tokens``; Anthropic ``cache_read_input_tokens``).
    Track them, or the spend most likely to surprise you stays invisible.
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
    """Whose spend an event represents.

    ``run_id`` ties every model, tool, and delegation event into a single run.
    ``parent_run`` links a delegated child run back to its caller, preserving cost
    lineage across an agent-to-agent hop.
    """

    user: str
    agent: str
    run_id: str
    parent_run: str | None = None


# =========================================================================== #
# 2. TELEMETRY EVENTS  (Instrument -> Attribute)                          #
# =========================================================================== #
# One base, three concrete kinds. Subclass to add a kind — the pipeline never
# changes (open/closed). kw_only=True means a subclass may add *required* fields
# without hitting "non-default argument follows default argument".

class EventKind(str, Enum):
    """Discriminator for the concrete :class:`Event` subtypes."""

    MODEL = "model"
    TOOL = "tool"
    DELEGATION = "delegation"


@dataclass(frozen=True, kw_only=True)
class Event:
    """Base telemetry record. Do not instantiate directly — use a concrete subtype.

    ``cost_micros`` is filled by the :class:`Meter`; it is ``0`` for events that do
    not bill (e.g. a local tool call). ``kind`` is a class-level discriminator, not
    a constructor field.
    """

    attr: Attribution
    step: int
    ts: float
    cost_micros: Micros = 0
    kind: ClassVar[EventKind]


@dataclass(frozen=True, kw_only=True)
class ModelCall(Event):
    """A completed model call, with the provider-reported token usage."""

    kind: ClassVar[EventKind] = EventKind.MODEL
    provider: str = ""
    model: str = ""
    usage: Usage = field(default_factory=Usage)
    partial: bool = False  # True for a streaming delta; its cost is incremental, never a total


@dataclass(frozen=True, kw_only=True)
class ToolCall(Event):
    """A tool invocation.

    ``signature`` is a stable hash of ``(name, args)`` so detectors can spot a
    repeated call (a semantic loop) without re-hashing on every tick.
    """

    kind: ClassVar[EventKind] = EventKind.TOOL
    name: str = ""
    args: Mapping[str, object] = field(default_factory=dict)
    signature: str = ""


@dataclass(frozen=True, kw_only=True)
class Delegation(Event):
    """A hand-off to another agent.

    ``rolled_up_cost_micros`` is the child run's total cost, reported back up the
    A2A hop so the parent's budget reflects the whole run, not just its own calls.
    """

    kind: ClassVar[EventKind] = EventKind.DELEGATION
    target_agent: str = ""
    child_run: str = ""
    rolled_up_cost_micros: Micros = 0


@dataclass(frozen=True, kw_only=True)
class CallRequest:
    """A model call about to be dispatched, inspected by :meth:`Detector.pre_call`
    *before* any tokens are spent (budget gate, oversized-input guard)."""

    attr: Attribution
    provider: str
    model: str
    estimated_input_tokens: int = 0
    max_output_tokens: int | None = None  # the call's output cap; lets pre_call bound worst case


# =========================================================================== #
# 3. SIGNALS  (Enforce: Detector -> Policy)                                       #
# =========================================================================== #

class Severity(str, Enum):
    """How strongly a detector is reacting.

    ``WARN`` invites a corrective response; ``TRIP`` calls for a preventive one.
    """

    OK = "ok"
    WARN = "warn"
    TRIP = "trip"


@dataclass(frozen=True, kw_only=True)
class Signal:
    """A detection emitted by Analysis. Analysis *recommends*; Enforcement *decides*.

    ``evidence`` carries the numbers behind the call (repeat count, cost/step, …)
    for explainable decisions and audit trails.
    """

    detector: str
    severity: Severity
    run_id: str
    reason: str = ""
    evidence: Mapping[str, object] = field(default_factory=dict)


# =========================================================================== #
# 4. ACTIONS  (Enforce -> Connector OUT)                                  #
# =========================================================================== #

class ActionKind(str, Enum):
    """What Enforcement decides to do with a run.

    Add a kind here and handle it in :meth:`AgentControls.apply`; the connector
    signature does not change.
    """

    ALLOW = "allow"          # let it proceed (a no-op for the OUT connector)
    HALT = "halt"            # preventive: stop the run now
    THROTTLE = "throttle"    # corrective: slow down or queue (concurrency control)
    DOWNGRADE = "downgrade"  # corrective: switch to a cheaper model
    PAUSE = "pause"          # corrective: suspend for human-in-the-loop review


@dataclass(frozen=True, kw_only=True)
class Action:
    """The decision applied to a run. Optional fields carry kind-specific payloads."""

    kind: ActionKind
    run_id: str
    reason: str = ""
    downgrade_to: str | None = None  # for ActionKind.DOWNGRADE
    retry_after_s: float | None = None  # for ActionKind.THROTTLE


class Halt(BaseException):
    """Raised through the data plane's existing callback to abort a run.

    Extends ``BaseException``, not ``Exception``, so a framework's broad
    ``try/except Exception`` for flaky APIs cannot swallow it.

    Carries the deciding :class:`Action` so the boundary can return a structured
    "halted, here is the partial cost" response rather than a generic server error.
    """

    def __init__(self, action: Action) -> None:
        super().__init__(action.reason)
        self.action = action


# =========================================================================== #
# 5. MODULE 1: INSTRUMENT  (measure each call and price it)                   #
# =========================================================================== #

@runtime_checkable
class Instrument(Protocol):
    """Module 1. Measures each call and prices it into an :class:`Event`.

    ``price`` is the pluggable price book; it must **fail closed** (an unknown
    ``(provider, model)`` pair raises rather than returning zero). ``meter`` reads
    the usage totals (including ``cached`` and ``reasoning``), fills ``cost_micros``,
    and returns the priced ``Event``.
    """

    def price(self, provider: str, model: str, usage: Usage) -> Micros:
        """Cost of one call in micro dollars. Fail closed on unknown models."""
        ...

    def meter(self, kind: str, provider: str, model: str, usage: Usage,
              step: int, ts: float, partial: bool = False) -> Event:
        """Build and price an Event. A streaming delta sets ``partial=True`` and
        carries only the incremental cost, so :meth:`Attribute.record` never
        double counts."""
        ...


# =========================================================================== #
# 6. MODULE 2: ATTRIBUTE  (tag each event, remember the run's totals)         #
# =========================================================================== #

@runtime_checkable
class Attribute(Protocol):
    """Module 2. Stamps each event with who it belongs to and keeps the ledger.

    ``open_run`` starts a run and returns its ``run_id``. ``record`` stamps the
    event's :class:`Attribution`, stores it, and updates the running totals
    atomically (safe under concurrent calls in one run, locked per ``run_id``).
    ``view`` returns the read-only :class:`LedgerView` that Enforce reads.
    """

    def open_run(self, user: str, agent: str,
                 budget_micros: Micros | None = None,
                 parent_run: str | None = None) -> str: ...

    def record(self, event: Event, run_id: str) -> Event: ...

    def view(self) -> LedgerView: ...


@runtime_checkable
class LedgerView(Protocol):
    """Read-only view of run state that Attribute hands to Enforce. Detectors never
    mutate it.

    Complexity contract — keep detector hot paths cheap:

    * :meth:`cost_micros`, :meth:`step_count`, :meth:`cache_hit_rate` are **O(1)**
      running aggregates the ledger maintains as events arrive. Prefer these.
    * :meth:`recent` is **O(window)** — bounded — for loop and velocity detectors
      that only need the tail of the history.
    * :meth:`events` is **O(N)** — the full scan. It is an escape hatch for rare
      whole-run analysis; do not call it on every ``observe``.
    """

    def cost_micros(self, run_id: str) -> Micros: ...

    def step_count(self, run_id: str) -> int: ...

    def cache_hit_rate(self, run_id: str, window: int) -> float: ...

    def recent(self, run_id: str, n: int) -> Sequence[Event]: ...

    def events(self, run_id: str) -> Sequence[Event]: ...


# =========================================================================== #
# 7. MODULE 3: ENFORCE  (extension points: Detector, Policy — ABCs)    #
# =========================================================================== #

class Detector(ABC):
    """A breaker / signal source.

    Each hook is ``(input, read-only view) -> Signal | None``. Override only the
    hooks relevant to your signal; the rest are no-ops. Detectors read ledger state
    but never write it, which keeps them trivial to unit-test.

    Performance: prefer ``view.recent(...)`` and the O(1) aggregates over
    ``view.events(...)`` so evaluation stays O(window), not O(N) per event.
    """

    name: str = "detector"

    def pre_call(self, request: CallRequest, view: LedgerView) -> Signal | None:
        """Inspect a call before dispatch (budget gate, oversized input)."""
        return None

    def observe(self, event: Event, view: LedgerView) -> Signal | None:
        """Inspect a completed event (loops, velocity, cache decay, budget)."""
        return None

    def tick(self, now: float, view: LedgerView) -> Signal | None:
        """Inspect on a clock, independent of events (timeouts, stalls)."""
        return None

    def reset(self, run_id: str) -> None:
        """Drop any per-run state held for ``run_id``."""
        return None


class Policy(ABC):
    """Maps a :class:`Signal` to an :class:`Action`.

    Preventive policies return ``HALT``; corrective policies return ``DOWNGRADE``,
    ``THROTTLE``, or ``PAUSE``. Policies compose — the host decides how to combine
    their actions (for example, first non-``ALLOW`` wins).
    """

    name: str = "policy"

    @abstractmethod
    def decide(self, signal: Signal, view: LedgerView) -> Action: ...


# =========================================================================== #
# 8. CONNECTORS  (the only two touch-points with the data plane)             #
# =========================================================================== #

@runtime_checkable
class TelemetrySource(Protocol):
    """Connector IN. Emits normalised events into the control plane.

    A brownfield adapter maps an existing agent callback to :class:`Event` and
    calls :meth:`emit`; greenfield code calls :meth:`emit` directly.
    """

    def emit(self, event: Event) -> None: ...


@runtime_checkable
class AgentControls(Protocol):
    """Connector OUT. The single channel the data plane exposes so the control
    plane can act on a run.

    One method, polymorphic on ``action.kind`` — adding an :class:`ActionKind`
    never changes this signature. The host dispatches every non-``ALLOW`` action
    here. An implementation handles the kinds it supports and should treat an
    unsupported kind by **failing closed** (escalate to ``HALT``) rather than
    silently ignoring it.

    Brownfield ``apply`` for ``HALT`` raises :class:`Halt` through the agent's
    existing callback, requiring no change to agent logic. Greenfield
    implementations may also honour ``THROTTLE`` / ``DOWNGRADE`` / ``PAUSE`` when
    backed by a checkpointable runtime.
    """

    def apply(self, action: Action) -> None: ...


# =========================================================================== #
# 9. FACADE  (greenfield ergonomics; brownfield uses the adapters above)     #
# =========================================================================== #

class ControlPlane(Protocol):
    """Top-level entry point that wires the modules and connectors together."""

    def run(
        self,
        *,
        user: str,
        agent: str,
        budget_micros: Micros | None = None,
        parent_run: str | None = None,
    ) -> RunContext:
        """Open a governed run (a context manager)."""
        ...

    def wrap(self, client: T) -> T:
        """Return a metered, pre-call-guarded wrapper around a model client.

        Typed ``T -> T`` so the wrapped client keeps the original's type, and the
        IDE keeps autocomplete and signature help for it.
        """
        ...

    def on_step(self) -> StepCallback:
        """Return a plain callback to pass into an existing agent's step hook,
        e.g. ``agent.run(task, on_step=cp.on_step())``.

        The framework invokes it as a function with its own step object; the
        callback maps that to an ``Event`` and emits it. It is a ``Callable``,
        not a bare ``TelemetrySource``, so frameworks can call it directly.
        """
        ...

    def register(self, *items: Detector | Policy) -> None:
        """Register detectors and policies (the extensibility surface)."""
        ...

    def tick(self) -> None:
        """Advance clock-driven detectors. Call on a timer."""
        ...


class RunContext(Protocol):
    """A single governed run. Use as a context manager."""

    run_id: str

    def record_tool(self, name: str, args: Mapping[str, object]) -> None:
        """Feed a tool invocation to the behavioural detectors."""
        ...

    def __enter__(self) -> RunContext: ...

    def __exit__(self, *exc: object) -> bool: ...
