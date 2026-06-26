"""Engine — the policy execution harness (the LLD's Enforce module + OUT connector).

The Governor is the *mechanism*; detectors and policies are the *policy*. It owns the
three governed moments and nothing else:

    pre_call(request)  — before spend: worst-case, budget gate, oversized input
    observe(obs)       — after each crossing: record to ledger, then detect → decide → apply
    tick(now)          — on a clock: stalls, timeouts

Execution order inside a moment (worst-first):
  1. every registered Detector's hook runs, read-only, against the LedgerView → Signals
  2. Signals are sorted TRIP > WARN > OK so a preventive stop is decided before a steer
  3. each Signal is routed to its paired Policy (by name) → an Action
  4. the Action is dispatched to the OUT connector; HALT marks the ledger flag *before*
     it is applied, so the kill switch is armed even if the raise is later swallowed

Kill switch: before any moment, a run already flagged halted is refused at the IN edge —
this is what makes HALT sticky and idempotent across A2A.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Sequence, runtime_checkable

from tokenops.control.core import (
    Action,
    ActionKind,
    CallRequest,
    Detector,
    Halt,
    Observation,
    Policy,
    Severity,
    Signal,
)
from tokenops.control.ledger import Ledger

_SEVERITY_RANK = {Severity.OK: 0, Severity.WARN: 1, Severity.TRIP: 2}


class Throttled(Exception):
    """Raised by an OUT connector for REJECT/QUEUE — a *retryable* backpressure signal.

    Unlike :class:`Halt` (a ``BaseException`` that aborts the run), this is an ordinary
    ``Exception`` the caller is meant to catch and back off / resubmit on.
    """

    def __init__(self, action: Action) -> None:
        super().__init__(action.reason)
        self.action = action


# =========================================================================== #
# OUT connector                                                               #
# =========================================================================== #

@runtime_checkable
class AgentControls(Protocol):
    """Connector OUT — the single channel the control plane uses to act on a run. One
    method, polymorphic on ``action.kind``; adding an ActionKind never changes it."""

    def apply(self, action: Action) -> None: ...


class RaiseControls:
    """Brownfield OUT connector. Drops into a vanilla agent with no logic change.

    ``HALT`` raises :class:`Halt` (a ``BaseException``) through the agent's existing
    callback, unwinding its loop. Corrective kinds (MUTATE/INJECT/RETRY/QUEUE/CANCEL)
    need a checkpointable runtime or a call wrapper to honour; a vanilla agent cannot, so
    they **fail closed** — escalate to HALT rather than silently vanish.
    """

    def apply(self, action: Action) -> None:
        if action.kind is ActionKind.ALLOW:
            return
        if action.kind is ActionKind.HALT:
            raise Halt(action)
        raise Halt(Action(
            kind=ActionKind.HALT, run_id=action.run_id,
            reason=f"{action.kind.value} unsupported by RaiseControls; failing closed",
        ))


@dataclass
class _ResolvedCall:
    """Mutations the pre_call hooks decided for the call about to be dispatched."""

    model_override: str | None = None
    max_output_tokens: int | None = None


@dataclass
class ApplyControls:
    """Greenfield OUT connector — actually *applies* corrective controls, for use behind a
    provider wrap (see ``integration.wrap_complete``).

    HALT still raises; REJECT/QUEUE raise :class:`Throttled`. The rest are recorded so the
    wrap can act on them:
      * MUTATE  → ``call`` overrides (model swap, output cap) + any prompt directive carried
      * INJECT  → ``carry`` messages prepended to the next dispatch
      * RETRY   → ``retry`` flag (the wrap may re-issue; streaming CANCEL is out of scope here)
    """

    carry: list[str] = field(default_factory=list)
    call: _ResolvedCall = field(default_factory=_ResolvedCall)
    retry: bool = False

    def begin_call(self) -> None:
        """Reset per-call mutation state before a pre_call pass (``carry`` persists across
        calls until consumed by the next dispatch)."""
        self.call = _ResolvedCall()
        self.retry = False

    def apply(self, action: Action) -> None:
        kind = action.kind
        if kind is ActionKind.ALLOW:
            return
        if kind is ActionKind.HALT:
            raise Halt(action)
        if kind in (ActionKind.REJECT, ActionKind.QUEUE):
            raise Throttled(action)
        if kind is ActionKind.MUTATE:
            if action.downgrade_to:
                self.call.model_override = action.downgrade_to
            if action.max_output_tokens is not None:
                self.call.max_output_tokens = action.max_output_tokens
            if action.inject_message:  # e.g. compaction directive
                self.carry.append(action.inject_message)
        elif kind is ActionKind.INJECT:
            if action.inject_message:
                self.carry.append(action.inject_message)
        elif kind is ActionKind.RETRY:
            self.retry = True
        # CANCEL is stream-only; a synchronous wrap has nothing to tear down.


# =========================================================================== #
# Governor — the harness                                                       #
# =========================================================================== #

class Governor:
    """Wires ledger + detectors + policies + OUT connector into the three moments.

    Detectors and their policies are registered as pairs and routed by name
    (``detector.name == policy.name``), so each policy only ever sees signals from its own
    detector. That keeps the LLD's per-policy ``(detect, fix)`` rows independent.
    """

    def __init__(self, ledger: Ledger, controls: AgentControls | None = None) -> None:
        self.ledger = ledger
        self.controls: AgentControls = controls or RaiseControls()
        self._detectors: list[Detector] = []
        self._policy_by_name: dict[str, Policy] = {}

    def register(self, detector: Detector, policy: Policy) -> None:
        """Register one policy template: a detector and the policy that decides its signals."""
        if detector.name != policy.name:
            raise ValueError(
                f"detector/policy name mismatch: {detector.name!r} != {policy.name!r}; "
                "a template's detector and policy must share a name so signals route correctly"
            )
        self._detectors.append(detector)
        self._policy_by_name[detector.name] = policy

    # ---- the three moments ------------------------------------------------ #

    def pre_call(self, request: CallRequest) -> None:
        self._refuse_if_halted(request.attr.run_id)
        signals = [s for d in self._detectors
                   if (s := d.pre_call(request, self.ledger)) is not None]
        self._enforce(signals)

    def observe(self, obs: Observation):
        self._refuse_if_halted(obs.attr.run_id)
        step = self.ledger.record(obs)  # Attribute: price → spent → append → steps++
        signals = [s for d in self._detectors
                   if (s := d.observe(obs.attr, step, self.ledger)) is not None]
        self._enforce(signals)
        return step

    def tick(self, now: float) -> None:
        signals = [s for d in self._detectors
                   if (s := d.tick(now, self.ledger)) is not None]
        self._enforce(signals)

    # ---- internals -------------------------------------------------------- #

    def _refuse_if_halted(self, run_id: str) -> None:
        """The IN-edge kill switch: once halted, every later call is refused — even if the
        agent caught the first Halt and kept going."""
        if self.ledger.is_halted(run_id):
            self.controls.apply(Action(
                kind=ActionKind.HALT, run_id=run_id,
                reason="run already halted; refusing further calls",
            ))

    def _enforce(self, signals: Sequence[Signal]) -> None:
        for sig in sorted(signals, key=lambda s: _SEVERITY_RANK[s.severity], reverse=True):
            policy = self._policy_by_name.get(sig.detector)
            if policy is None:
                continue  # a detector with no paired policy is observe-only telemetry
            action = policy.decide(sig, self.ledger)
            if action.kind is ActionKind.HALT:
                # set the durable flag BEFORE applying, so the kill switch survives a
                # swallowed raise. Idempotent — marking twice is harmless.
                self.ledger.mark_halted(action.run_id, action.reason)
            self.controls.apply(action)  # may raise Halt and unwind the agent loop
