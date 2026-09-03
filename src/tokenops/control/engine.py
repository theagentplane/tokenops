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

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

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
        raise Halt(
            Action(
                kind=ActionKind.HALT,
                run_id=action.run_id,
                reason=f"{action.kind.value} unsupported by RaiseControls; failing closed",
            )
        )


@dataclass
class _ResolvedCall:
    """Mutations the pre_call hooks decided for the call about to be dispatched."""

    model_override: str | None = None
    max_output_tokens: int | None = None
    compact: bool = False  # deep MUTATE: rewrite the outgoing messages (context_compaction)


@dataclass
class ApplyControls:
    """Greenfield OUT connector — actually *applies* corrective controls, for use behind a
    provider wrap (see ``integration.wrap_complete``).

    HALT still raises; REJECT/QUEUE raise :class:`Throttled`. The rest are recorded so the
    wrap can act on them:
      * MUTATE  → ``call`` overrides (model swap, output cap) + any prompt directive carried
      * INJECT  → ``carry`` messages appended as final user turns on the next dispatch
      * RETRY   → ``retry`` flag (the wrap may re-issue; streaming CANCEL is out of scope here)

    One ``observe`` pass can hand several policies' actions to the same call, so this
    connector merges rather than overwrites. Two rules keep that merge safe:

    **Caps only tighten.** ``max_output_tokens`` takes the ``min`` of what any policy asked
    for. Without this, a looser cap applied later silently undoes a tighter one, and the
    order is severity rank then detector registration, which no user controls.

    **Directives are bounded.** ``carry`` dedups and stops at ``max_carry``. ``cost_guard``
    fires *because* spend is high, so an unbounded pile of steer messages would add prompt
    tokens at exactly the wrong moment.
    """

    carry: list[str] = field(default_factory=list)
    event_log: list[Action] = field(default_factory=list)
    call: _ResolvedCall = field(default_factory=_ResolvedCall)
    retry: bool = False
    tool_result_override: str | None = None  # deep INJECT: substitute the last tool result
    max_carry: int = 3  # steer messages carried onto one dispatch; the rest are dropped
    dropped_carry: int = 0  # how many were dropped, for the dashboard

    def begin_call(self) -> None:
        """Reset per-call mutation state before a pre_call pass (``carry`` persists across
        calls until consumed by the next dispatch)."""
        self.call = _ResolvedCall()
        self.retry = False
        self.dropped_carry = 0

    def take_tool_result(self) -> str | None:
        """Consume a pending tool-result substitution (the agent calls this after a tool
        crossing). One-shot — cleared on read."""
        val = self.tool_result_override
        self.tool_result_override = None
        return val

    def apply(self, action: Action) -> None:
        kind = action.kind
        if kind is ActionKind.ALLOW:
            return
        self.event_log.append(action)
        if kind is ActionKind.HALT:
            raise Halt(action)
        if kind in (ActionKind.REJECT, ActionKind.QUEUE):
            raise Throttled(action)
        if kind is ActionKind.MUTATE:
            if action.downgrade_to:
                self.call.model_override = action.downgrade_to
            if action.max_output_tokens is not None:
                self._tighten_output_cap(action.max_output_tokens)
            if action.compact:  # deep prompt compaction (rewrite messages in the wrap)
                self.call.compact = True
            if action.inject_message:  # compaction directive / steer
                self._carry(action.inject_message)
        elif kind is ActionKind.INJECT:
            if action.replace_tool_result and action.inject_message:  # deep tool-result swap
                self.tool_result_override = action.inject_message
            elif action.inject_message:
                self._carry(action.inject_message)
        elif kind is ActionKind.RETRY:
            self.retry = True
        # CANCEL is stream-only; a synchronous wrap has nothing to tear down.

    def _tighten_output_cap(self, requested: int) -> None:
        """Take the tightest cap any policy asked for on this call.

        Never widen: a policy asking for a bigger cap than one already set is asking to
        undo another policy's restriction, and the winner would otherwise be decided by
        detector registration order.
        """
        current = self.call.max_output_tokens
        self.call.max_output_tokens = requested if current is None else min(current, requested)

    def _carry(self, message: str) -> None:
        """Queue a steer message, deduped and bounded by ``max_carry``."""
        if message in self.carry:
            return
        if len(self.carry) >= self.max_carry:
            self.dropped_carry += 1
            return
        self.carry.append(message)


@dataclass
class PreviewControls(ApplyControls):
    """OUT connector for preview mode — record detect/decide without enforcing."""

    actions: list[Action] = field(default_factory=list)

    def apply(self, action: Action) -> None:
        # Preview mode is "detect + decide only": do not apply mutations/injections
        # (so governance OFF can still exceed caps for the demo) and do not raise.
        self.actions.append(action)

    def preview_summary(self) -> dict[str, Any]:
        return {
            "action_count": len(self.actions),
            "would_halt": any(a.kind is ActionKind.HALT for a in self.actions),
            "actions": [{"kind": a.kind.value, "reason": a.reason} for a in self.actions],
        }


def policy_hint_from_reason(reason: str) -> str:
    """Best-effort policy name for dashboard display."""
    r = reason.lower()
    if "worst-case" in r or "bounding to" in r or "output cap" in r:
        return "pre_call_worst_case"
    if "minimizing" in r or "budget pressure" in r:
        return "cost_guard"
    if "exhausted" in r or "no budget" in r:
        return "cost_budget"
    return "—"


def governance_events_payload(controls: ApplyControls | PreviewControls) -> list[dict[str, Any]]:
    """Serialize non-ALLOW governance actions for persistence and the dashboard."""
    actions = controls.actions if isinstance(controls, PreviewControls) else controls.event_log
    out: list[dict[str, Any]] = []
    for action in actions:
        if action.kind is ActionKind.ALLOW:
            continue
        row: dict[str, Any] = {
            "kind": action.kind.value,
            "reason": action.reason,
            "policy": policy_hint_from_reason(action.reason),
        }
        if action.inject_message:
            row["message"] = action.inject_message
        if action.max_output_tokens is not None:
            row["max_output_tokens"] = action.max_output_tokens
        out.append(row)
    return out


def halt_detector_from_events(events: Sequence[dict[str, Any]]) -> str | None:
    for ev in reversed(events):
        if ev.get("kind") == "halt":
            policy = ev.get("policy")
            return policy if policy and policy != "—" else None
    return None


# =========================================================================== #
# Governor — the harness                                                       #
# =========================================================================== #


class Governor:
    """Wires ledger + detectors + policies + OUT connector into the three moments.

    Detectors and their policies are registered as pairs and routed by name
    (``detector.name == policy.name``), so each policy only ever sees signals from its own
    detector. That keeps the LLD's per-policy ``(detect, fix)`` rows independent.
    """

    def __init__(
        self,
        ledger: Ledger,
        controls: AgentControls | None = None,
        *,
        enforce: bool = True,
    ) -> None:
        self.ledger = ledger
        self.controls: AgentControls = controls or RaiseControls()
        self.enforce = enforce
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
        signals = [
            s for d in self._detectors if (s := d.pre_call(request, self.ledger)) is not None
        ]
        self._enforce(signals)

    def observe(self, obs: Observation):
        self._refuse_if_halted(obs.attr.run_id)
        step = self.ledger.record(obs)  # Attribute: price → spent → append → steps++
        signals = [
            s for d in self._detectors if (s := d.observe(obs.attr, step, self.ledger)) is not None
        ]
        self._enforce(signals)
        return step

    def tick(self, now: float) -> None:
        signals = [s for d in self._detectors if (s := d.tick(now, self.ledger)) is not None]
        self._enforce(signals)

    # ---- internals -------------------------------------------------------- #

    def _refuse_if_halted(self, run_id: str) -> None:
        """The IN-edge kill switch: once halted, every later call is refused — even if the
        agent caught the first Halt and kept going."""
        if self.ledger.is_halted(run_id):
            self.controls.apply(
                Action(
                    kind=ActionKind.HALT,
                    run_id=run_id,
                    reason="run already halted; refusing further calls",
                )
            )

    def _enforce(self, signals: Sequence[Signal]) -> None:
        for sig in sorted(signals, key=lambda s: _SEVERITY_RANK[s.severity], reverse=True):
            policy = self._policy_by_name.get(sig.detector)
            if policy is None:
                continue  # a detector with no paired policy is observe-only telemetry
            action = policy.decide(sig, self.ledger)
            if action.kind is ActionKind.HALT and self.enforce:
                # set the durable flag BEFORE applying, so the kill switch survives a
                # swallowed raise. Idempotent — marking twice is harmless.
                self.ledger.mark_halted(action.run_id, action.reason)
            self.controls.apply(action)  # may raise Halt and unwind the agent loop
