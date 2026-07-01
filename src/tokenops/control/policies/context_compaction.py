"""context_compaction — default; needs a prompt-assembly hook.

LLD row:
    Detect: est_input ≥ ctx_max OR est_input rising over recent(run, W) (estimate from last
            llm step's usage.input, never tokenize on the hot path).
    Fix:    MUTATE the outgoing prompt: (1) move volatile values below the static prefix to
            restore the prompt-cache discount, (2) dedup tool outputs by hash, (3) summarize
            only filler, pinning system prompt, schema, constraints, state. No hook → degrade
            to telemetry, never HALT. Full history stays in the unbounded window.

Fires at pre_call (it shapes the *next* prompt). Without an assembly hook it can only
observe — so it emits the signal for the dashboard and takes no action. It never HALTs.
"""

from __future__ import annotations

from tokenops.control.core import (
    Action,
    ActionKind,
    CallRequest,
    Detector,
    LedgerView,
    Policy,
    Severity,
    Signal,
)


class ContextCompactionDetector(Detector):
    """WARN when the estimated input is at/over the context ceiling, or rising across the
    recent llm steps."""

    name = "context_compaction"

    def __init__(self, ctx_max: int, *, window: int = 4) -> None:
        self.ctx_max = ctx_max
        self.window = window

    def pre_call(self, request: CallRequest, view: LedgerView) -> Signal | None:
        est = request.estimated_input_tokens
        recent_llm = [s for s in view.recent(request.attr.run_id, self.window)
                      if s.node_type == "llm" and s.usage is not None]
        rising = (
            len(recent_llm) >= 2
            and all(a.usage.input <= b.usage.input for a, b in zip(recent_llm, recent_llm[1:]))
            and recent_llm[-1].usage.input > recent_llm[0].usage.input
        )
        if est >= self.ctx_max or (rising and est >= self.ctx_max // 2):
            return Signal(
                detector=self.name, severity=Severity.WARN, run_id=request.attr.run_id,
                reason=f"est_input {est} vs ctx_max {self.ctx_max}" + (" (rising)" if rising else ""),
                evidence={"est_input": est, "ctx_max": self.ctx_max, "rising": rising},
            )
        return None


class ContextCompactionPolicy(Policy):
    """MUTATE the prompt if an assembly hook exists; otherwise telemetry-only (ALLOW). Never
    HALT — losing the cache discount or a bloated prompt is not a reason to kill a run."""

    name = "context_compaction"

    def __init__(self, has_hook: bool = True) -> None:
        self.has_hook = has_hook

    def decide(self, signal: Signal, view: LedgerView) -> Action:
        if not self.has_hook:
            return Action(kind=ActionKind.ALLOW, run_id=signal.run_id,
                          reason=f"{signal.reason} (no assembly hook — telemetry only)")
        return Action(
            kind=ActionKind.MUTATE, run_id=signal.run_id, reason=signal.reason, compact=True,
            inject_message="COMPACT: move volatile values below the static prefix, dedup tool "
                           "outputs by hash, summarize filler; pin system/schema/constraints/state.",
        )


def build(ctx_max: int, *, window: int = 4, has_hook: bool = True) -> tuple[Detector, Policy]:
    return ContextCompactionDetector(ctx_max, window=window), ContextCompactionPolicy(has_hook)
