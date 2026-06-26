"""tool_output_cap — strong, always-on. Stop a huge tool payload from entering context.

LLD row:
    Detect: estimate tokens with a content-aware divisor — len/4 for natural-language text,
            len/2.8 for JSON/structured/code; trip if est_tokens ≥ cap. Unknown/structured
            defaults to the smaller divisor (2.8) so a large payload is never under-counted.
            No tokenizer on the hot path.
    Fix:    INJECT — offload the full payload to the store (handle); substitute a descriptor
            {size, schema, count, handle} plus an instruction to paginate or filter. Never
            feed back a sliced payload as whole.

Cheap `len()` detect; the auxiliary cost is negligible versus feeding a giant payload to the
model on the next turn.
"""

from __future__ import annotations

import hashlib

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
from tokenops.control.policies._util import est_tokens


def _handle(payload: object) -> str:
    return "store://" + hashlib.sha256(repr(payload).encode()).hexdigest()[:16]


class ToolOutputCapDetector(Detector):
    """WARN when a tool result's estimated tokens exceed the cap."""

    name = "tool_output_cap"

    def __init__(self, cap_tokens: int = 8000) -> None:
        self.cap_tokens = cap_tokens

    def observe(self, attr: Attribution, step: BoundaryStep, view: LedgerView) -> Signal | None:
        if step.node_type != "tool":
            return None
        est = est_tokens(step.output)
        if est >= self.cap_tokens:
            count = len(step.output) if isinstance(step.output, (list, dict)) else None
            return Signal(
                detector=self.name, severity=Severity.WARN, run_id=attr.run_id,
                reason=f"tool '{step.boundary_id}' output ≈{est} tokens ≥ cap {self.cap_tokens}",
                evidence={
                    "est_tokens": est, "cap": self.cap_tokens,
                    "size": est, "count": count, "handle": _handle(step.output),
                },
            )
        return None


class ToolOutputCapPolicy(Policy):
    """Substitute a descriptor for the oversized payload; the full thing lives behind a
    handle. Never HALT — this is a corrective shaping of context."""

    name = "tool_output_cap"

    def decide(self, signal: Signal, view: LedgerView) -> Action:
        ev = signal.evidence
        return Action(
            kind=ActionKind.INJECT, run_id=signal.run_id, reason=signal.reason,
            inject_message=(
                f"TOOL OUTPUT OFFLOADED: ~{ev['est_tokens']} tokens, count={ev['count']}, "
                f"handle={ev['handle']}. Paginate or filter via the handle instead of "
                f"requesting the whole payload."
            ),
        )


def build(cap_tokens: int = 8000) -> tuple[Detector, Policy]:
    return ToolOutputCapDetector(cap_tokens), ToolOutputCapPolicy()
