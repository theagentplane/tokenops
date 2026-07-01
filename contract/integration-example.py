"""Reference integration adapters for TokenOps — greenfield and brownfield.

These are *illustrative* reference implementations built only on
``tokenops.contracts``. Copy them into your project and adapt. They carry no
third-party dependencies, so this file imports and runs standalone; comments mark
exactly where your real agent / SDK plugs in.

Run it directly to watch a simulated search loop trip a breaker::

    python integration_example.py
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Mapping

try:  # in your package this is: from tokenops.contracts import ...
    from tokenops.contracts import (
        Action, ActionKind, Attribution, CallRequest, Detector, Event, Halt,
        LedgerView, Micros, ModelCall, Policy, Severity, Signal, ToolCall, Usage,
    )
except ImportError:  # running standalone from this folder
    from contracts import (
        Action, ActionKind, Attribution, CallRequest, Detector, Event, Halt,
        LedgerView, Micros, ModelCall, Policy, Severity, Signal, ToolCall, Usage,
    )


def toy_cost(input_tokens: int, output_tokens: int) -> Micros:
    """Stand-in price table: 1 micro per input token, 4 per output token."""
    return input_tokens * 1 + output_tokens * 4


def otel_attributes(event: Event) -> dict:
    """Map an Event to OpenTelemetry GenAI span attributes (the wire format)."""
    attrs = {"gen_ai.conversation.id": event.attr.run_id}
    if isinstance(event, ModelCall):
        attrs.update({
            "gen_ai.operation.name": "chat",
            "gen_ai.provider.name": event.provider,
            "gen_ai.request.model": event.model,
            "gen_ai.usage.input_tokens": event.usage.input,
            "gen_ai.usage.output_tokens": event.usage.output,
        })
    elif isinstance(event, ToolCall):
        attrs.update({"gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": event.name})
    return attrs


# --------------------------------------------------------------------------- #
# A minimal ledger that satisfies LedgerView with O(1) aggregates.            #
# Real implementations would persist; this keeps everything in memory.        #
# --------------------------------------------------------------------------- #

class InMemoryLedger:
    """Maintains running aggregates as events arrive, so detectors read O(1)/O(window)."""

    def __init__(self) -> None:
        self._events: dict[str, list[Event]] = defaultdict(list)
        self._cost: dict[str, Micros] = defaultdict(int)
        self._cache_hits: dict[str, int] = defaultdict(int)
        self._cache_total: dict[str, int] = defaultdict(int)
        self._halted: set[str] = set()

    # write side (used by the Meter / governor, not by detectors)
    def add(self, event: Event) -> None:
        rid = event.attr.run_id
        self._events[rid].append(event)
        self._cost[rid] += event.cost_micros  # partials carry deltas, so adding never double counts
        if isinstance(event, ModelCall):  # track cache hit rate incrementally
            self._cache_total[rid] += 1
            if event.usage.cached > 0:
                self._cache_hits[rid] += 1

    def mark_halted(self, run_id: str) -> None:
        self._halted.add(run_id)

    def is_halted(self, run_id: str) -> bool:
        return run_id in self._halted

    # LedgerView read side
    def cost_micros(self, run_id: str) -> Micros:
        return self._cost[run_id]

    def step_count(self, run_id: str) -> int:
        return len(self._events[run_id])

    def cache_hit_rate(self, run_id: str, window: int) -> float:
        total = self._cache_total[run_id]
        return (self._cache_hits[run_id] / total) if total else 1.0

    def recent(self, run_id: str, n: int):
        return self._events[run_id][-n:]

    def events(self, run_id: str):
        return list(self._events[run_id])


# --------------------------------------------------------------------------- #
# Two example detectors. Each overrides ONE hook — everything else is no-op.  #
# Note they read view.recent(...) / aggregates, never view.events(...).       #
# --------------------------------------------------------------------------- #

class SemanticLoop(Detector):
    """TRIP when the same tool signature repeats inside a sliding window."""

    name = "semantic_loop"

    def __init__(self, window: int = 5, repeats: int = 3) -> None:
        self.window, self.repeats = window, repeats

    def observe(self, event: Event, view: LedgerView) -> Signal | None:
        if not isinstance(event, ToolCall):
            return None
        recent = [e for e in view.recent(event.attr.run_id, self.window)
                  if isinstance(e, ToolCall)]
        count = sum(1 for e in recent if e.signature == event.signature)
        if count >= self.repeats:
            return Signal(detector=self.name, severity=Severity.TRIP,
                          run_id=event.attr.run_id,
                          reason=f"tool '{event.name}' repeated {count}x in last {self.window}",
                          evidence={"signature": event.signature, "count": count})
        return None


class BudgetCap(Detector):
    """Preventive budget. ``pre_call`` refuses on worst case; ``observe`` trips on actual spend."""

    name = "budget_cap"

    def __init__(self, limit_micros: Micros, cost=toy_cost) -> None:
        self.limit = limit_micros
        self.cost = cost

    def pre_call(self, request: CallRequest, view: LedgerView) -> Signal | None:
        # worst case = spent so far + cost(estimated input) + cost(max output cap)
        spent = view.cost_micros(request.attr.run_id)
        worst = spent + self.cost(request.estimated_input_tokens, request.max_output_tokens or 0)
        if worst >= self.limit:
            return Signal(detector=self.name, severity=Severity.TRIP, run_id=request.attr.run_id,
                          reason=f"worst-case cost {worst} >= budget {self.limit} (micro-USD)",
                          evidence={"spent": spent, "worst_case": worst, "limit": self.limit})
        return None

    def observe(self, event: Event, view: LedgerView) -> Signal | None:
        spent = view.cost_micros(event.attr.run_id)
        if spent >= self.limit:
            return Signal(detector=self.name, severity=Severity.TRIP, run_id=event.attr.run_id,
                          reason=f"run cost {spent} >= budget {self.limit} (micro-USD)",
                          evidence={"spent_micros": spent, "limit_micros": self.limit})
        return None


# --------------------------------------------------------------------------- #
# One example policy + the OUT connector.                                     #
# --------------------------------------------------------------------------- #

class HaltOnTrip(Policy):
    """Preventive: any TRIP becomes a HALT; anything else is ALLOW."""

    name = "halt_on_trip"

    def decide(self, signal: Signal, view: LedgerView) -> Action:
        if signal.severity is Severity.TRIP:
            return Action(kind=ActionKind.HALT, run_id=signal.run_id, reason=signal.reason)
        return Action(kind=ActionKind.ALLOW, run_id=signal.run_id)


class RaiseControls:
    """AgentControls OUT connector (brownfield).

    Supports HALT by raising :class:`Halt` through the agent's existing callback.
    Unsupported corrective kinds fail closed (escalate to HALT) rather than vanish.
    """

    def apply(self, action: Action) -> None:
        if action.kind is ActionKind.ALLOW:
            return
        if action.kind is ActionKind.HALT:
            raise Halt(action)
        # Greenfield runtimes would handle THROTTLE/DOWNGRADE/PAUSE here. A vanilla
        # agent cannot, so fail closed:
        raise Halt(Action(kind=ActionKind.HALT, run_id=action.run_id,
                          reason=f"{action.kind.value} unsupported here; halting"))


# --------------------------------------------------------------------------- #
# The Governor: ties meter + detectors + policy + controls into the 3 hooks.  #
# This is the small amount of glue both greenfield and brownfield share.      #
# --------------------------------------------------------------------------- #

class Governor:
    def __init__(self, detectors, policy: Policy, controls) -> None:
        self.detectors = list(detectors)
        self.policy = policy
        self.controls = controls
        self.ledger = InMemoryLedger()

    def _refuse_if_halted(self, run_id: str) -> None:
        # IN-connector kill switch: once a run is halted, refuse every later call,
        # even if the agent caught the first Halt and kept going.
        if self.ledger.is_halted(run_id):
            self.controls.apply(Action(kind=ActionKind.HALT, run_id=run_id,
                                       reason="run already halted; refusing further calls"))

    def _enforce(self, signals: list[Signal]) -> None:
        # worst-first: TRIP beats WARN beats OK
        for sig in sorted(signals, key=lambda s: ["ok", "warn", "trip"].index(s.severity.value),
                          reverse=True):
            action = self.policy.decide(sig, self.ledger)
            if action.kind is ActionKind.HALT:
                self.ledger.mark_halted(action.run_id)  # set the flag before we raise
            self.controls.apply(action)

    def pre_call(self, request: CallRequest) -> None:
        self._refuse_if_halted(request.attr.run_id)
        sigs = [s for d in self.detectors if (s := d.pre_call(request, self.ledger))]
        self._enforce(sigs)

    def observe(self, event: Event) -> Event:
        self._refuse_if_halted(event.attr.run_id)
        self.ledger.add(event)  # the Meter would price it first; here cost is pre-filled
        sigs = [s for d in self.detectors if (s := d.observe(event, self.ledger))]
        self._enforce(sigs)
        return event


def tool_signature(name: str, args: Mapping[str, object]) -> str:
    payload = json.dumps([name, args], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


# =========================================================================== #
# BROWNFIELD: drop into an existing vanilla agent, no agent-logic change.     #
# =========================================================================== #
# The agent already emits a StepEvent for every model/search/delegate action and
# accepts an `on_step` callback. We adapt that callback; we do not touch the loop.

@dataclass
class _StepEventLike:
    """Stand-in for tokenops.agents.types.StepEvent (so this file runs standalone)."""
    agent: str
    action: str            # "model" | "search" | "delegate"
    query: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


def make_on_step(governor: Governor, attr: Attribution):
    """Return a callback to pass straight into the vanilla agent's `on_step=...`.

    It maps the agent's StepEvent into a contract Event and runs the hooks. If a
    breaker trips, ``Halt`` propagates out of the agent loop and aborts the run —
    which is exactly the brownfield control channel.
    """
    state = {"step": 0}

    def on_step(ev: _StepEventLike) -> None:  # signature matches the agent's callback
        state["step"] += 1
        if ev.action in ("search", "delegate"):
            event: Event = ToolCall(
                attr=attr, step=state["step"], ts=float(state["step"]),
                name=ev.action, args={"query": ev.query},
                signature=tool_signature(ev.action, {"query": ev.query}),
            )
        else:  # "model"  (cost would be priced by the Meter from real token usage)
            event = ModelCall(
                attr=attr, step=state["step"], ts=float(state["step"]),
                cost_micros=toy_cost(ev.input_tokens, ev.output_tokens),
                provider="openai", model="gpt-4o-mini",
                usage=Usage(input=ev.input_tokens, output=ev.output_tokens),
            )
        # On the wire this event is emitted as an OTel GenAI span: otel_attributes(event)
        governor.observe(event)

    return on_step


# =========================================================================== #
# GREENFIELD: write the agent against the control plane from day one.         #
# =========================================================================== #

class GreenfieldRun:
    """Minimal `with cp.run(...)` style context manager built on the same Governor."""

    def __init__(self, governor: Governor, attr: Attribution) -> None:
        self._gov, self._attr, self._step = governor, attr, 0
        self.run_id = attr.run_id

    def __enter__(self) -> "GreenfieldRun":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False  # let Halt propagate to the caller

    def record_tool(self, name: str, args: Mapping[str, object]) -> None:
        self._step += 1
        self._gov.observe(ToolCall(
            attr=self._attr, step=self._step, ts=float(self._step),
            name=name, args=args, signature=tool_signature(name, args),
        ))


# --------------------------------------------------------------------------- #
# Demo: simulate a leaky search loop and watch the breaker trip.              #
# --------------------------------------------------------------------------- #

def _demo() -> None:
    governor = Governor(
        detectors=[SemanticLoop(window=5, repeats=3), BudgetCap(limit_micros=500_000)],
        policy=HaltOnTrip(),
        controls=RaiseControls(),
    )
    attr = Attribution(user="alice", agent="research", run_id="run-001")

    print("BROWNFIELD — vanilla agent emits repeated searches via on_step:")
    on_step = make_on_step(governor, attr)
    sample = ModelCall(attr=attr, step=1, ts=1.0, cost_micros=toy_cost(2000, 200),
                       provider="openai", model="gpt-4o-mini", usage=Usage(input=2000, output=200))
    print(f"  each model call is emitted as an OTel span: {otel_attributes(sample)}")
    try:
        for i in range(10):
            on_step(_StepEventLike(agent="research", action="model",
                                   input_tokens=2000, output_tokens=200))
            on_step(_StepEventLike(agent="research", action="search", query="pricing"))
            print(f"  step {i + 1}: searched 'pricing' "
                  f"(run cost so far: ${governor.ledger.cost_micros('run-001') / 1e6:.4f})")
    except Halt as h:
        print(f"  >>> HALTED: {h.action.reason}")
        # kill switch: even if the agent had swallowed the Halt, the next call is refused
        try:
            on_step(_StepEventLike(agent="research", action="search", query="pricing"))
        except Halt as h2:
            print(f"  >>> kill switch: {h2.action.reason}")

    print("\nPRE-CALL GUARD — worst case refused before the call is made:")
    gov2 = Governor(detectors=[BudgetCap(limit_micros=10_000)], policy=HaltOnTrip(),
                    controls=RaiseControls())
    req = CallRequest(attr=Attribution(user="alice", agent="research", run_id="run-002"),
                      provider="openai", model="gpt-4o-mini",
                      estimated_input_tokens=1000, max_output_tokens=5000)
    try:
        gov2.pre_call(req)
    except Halt as h:
        print(f"  >>> refused before spending: {h.action.reason}")


if __name__ == "__main__":
    _demo()
