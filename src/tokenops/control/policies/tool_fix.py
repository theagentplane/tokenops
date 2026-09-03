"""tool_fix — cheap defensive check for hallucinated tool calls.

LLD row:
    Detect: name ∉ registry (O(1) hash) OR ¬valid(args, schema[name]); track fails(run)
    Fix:    INJECT a synthetic tool result {error, did_you_mean (edit-distance),
            available_tools} instead of executing, so the model self-corrects. After K
            identical failures, HALT.

Catches a bad tool name *before* the model burns an I/O round-trip, and breaks the loop if
the model keeps emitting the same bad call.
"""

from __future__ import annotations

from collections import defaultdict

from tokenops.control.core import (
    Action,
    ActionKind,
    Attribution,
    BoundaryStep,
    Detector,
    LedgerView,
    Policy,
    Severity,
    Signal,
)
from tokenops.control.policies._util import did_you_mean


class ToolFixDetector(Detector):
    """WARN on an invalid tool call (inject a correction); TRIP after K identical failures.

    Stateful: counts identical failing signatures per run. ``reset(run_id)`` clears it.
    """

    name = "tool_fix"

    def __init__(self, registry, schema: dict | None = None, k: int = 3) -> None:
        self.registry = set(registry)
        self.schema = schema or {}
        self.k = k
        self._fails: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def reset(self, run_id: str) -> None:
        self._fails.pop(run_id, None)

    def _invalid(self, name: str, args) -> str | None:
        if name not in self.registry:
            return "unknown_tool"
        required = self.schema.get(name, {}).get("required", [])
        missing = [k for k in required if k not in (args or {})]
        return f"missing_args:{missing}" if missing else None

    def observe(self, attr: Attribution, step: BoundaryStep, view: LedgerView) -> Signal | None:
        if step.node_type != "tool":
            return None
        name = str(step.input.get("name", step.boundary_id))
        args = step.input.get("args", {})
        problem = self._invalid(name, args)
        if problem is None:
            return None

        # count identical failures (same offending name) for this run
        fails = self._fails[attr.run_id]
        fails[name] += 1
        count = fails[name]
        suggestion = did_you_mean(name, self.registry)
        sev = Severity.TRIP if count >= self.k else Severity.WARN
        return Signal(
            detector=self.name,
            severity=sev,
            run_id=attr.run_id,
            reason=f"invalid tool call '{name}' ({problem}); attempt {count}/{self.k}",
            evidence={
                "name": name,
                "problem": problem,
                "count": count,
                "did_you_mean": suggestion,
                "available_tools": sorted(self.registry),
            },
        )


class ToolFixPolicy(Policy):
    name = "tool_fix"

    def decide(self, signal: Signal, view: LedgerView) -> Action:
        if signal.severity is Severity.TRIP:
            return Action(
                kind=ActionKind.HALT,
                run_id=signal.run_id,
                reason=f"tool_fix: {signal.evidence['count']} identical bad calls, halting",
            )
        ev = signal.evidence
        hint = f" did_you_mean={ev['did_you_mean']}" if ev.get("did_you_mean") else ""
        return Action(
            kind=ActionKind.INJECT,
            run_id=signal.run_id,
            reason=signal.reason,
            replace_tool_result=True,  # deep: substitute the synthetic error for the bad tool's result
            inject_message=(
                f"ERROR: {ev['problem']} for tool '{ev['name']}'.{hint} "
                f"available_tools={ev['available_tools']}"
            ),
        )


def build(registry, *, schema: dict | None = None, k: int = 3) -> tuple[Detector, Policy]:
    return ToolFixDetector(registry, schema, k), ToolFixPolicy()
