"""model_router — proactive model routing (route easy steps to a cheaper model).

Unlike ``cost_guard`` (which downgrades *reactively* under budget pressure), this routes
**every call by task complexity** at ``pre_call``: easy → cheap model, hard → strong model.
The complexity is a deterministic, model-free classification (``route_hint`` on the
``CallRequest``, set by the wrap via ``classify_complexity`` — the semantic-router pattern).

Effectiveness: coarse heuristic routing is fast and deterministic (ideal for a demo);
learned routers (RouteLLM) and cheap-first *cascades* are the accuracy upgrade. The fix
mechanism reuses the existing MUTATE ``model_override`` in ``wrap_complete``.
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


class ModelRouterDetector(Detector):
    """Emit a routing signal when the call's complexity implies a different model than the
    one requested."""

    name = "model_router"

    def __init__(self, easy_model: str, hard_model: str) -> None:
        self.easy_model = easy_model
        self.hard_model = hard_model

    def pre_call(self, request: CallRequest, view: LedgerView) -> Signal | None:
        target = self.hard_model if request.route_hint == "hard" else self.easy_model
        if target == request.model:
            return None  # already on the right tier
        return Signal(
            detector=self.name, severity=Severity.WARN, run_id=request.attr.run_id,
            reason=f"route {request.route_hint or 'easy'} → {target} (was {request.model})",
            evidence={"route": request.route_hint or "easy", "to": target, "from": request.model},
        )


class ModelRouterPolicy(Policy):
    name = "model_router"

    def decide(self, signal: Signal, view: LedgerView) -> Action:
        return Action(kind=ActionKind.MUTATE, run_id=signal.run_id, reason=signal.reason,
                      downgrade_to=str(signal.evidence["to"]))


def build(*, easy_model: str = "gpt-4o-mini", hard_model: str = "gpt-4o") -> tuple[Detector, Policy]:
    return ModelRouterDetector(easy_model, hard_model), ModelRouterPolicy()
