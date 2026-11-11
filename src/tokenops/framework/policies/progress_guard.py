"""progress_guard — the last-resort unstick. Default.

LLD row (Tier 1, in-path, deterministic):
    Detect: domain progress signal if exposed; exact repeat
            count in recent(run,W) of (signature, result_hash) ≥ K; SimHash near-duplicate
            on llm output.text; hang (now − last step ts > T) via tick.
    Fix:    INJECT a deterministic factual correction from the evidence; increment a
            correction counter; HALT only after K corrections with no progress. Require an
            unchanged result, not just a repeated call.

The key discriminator: a repeated *call* with a *changed* result is progress (do not trip);
only an unchanged (signature, result_hash) — or a near-duplicate llm output — is a stall.

Opt-in third detection (``input_repeats`` > 0): the newest message sent to the model is the
same text (exact, or SimHash within ``input_simhash_threshold`` when > 0) on at least
``input_repeats`` calls in the window, whatever the model replies or does. It catches an agent that varies its actions but is shown
the same screen every time.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from tokenops.framework.core import (
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
from tokenops.framework.observation_utils import short_hash
from tokenops.framework.policies._util import hamming, last_message_text, simhash64

# What stalled, per kind of check: "tool" = unchanged result, "output" = near-duplicate reply,
# "input" = the same input shown again.
_WHAT = {
    "tool": "repeated result",
    "output": "repeated model output",
    "input": "unchanged input",
}
_NUDGE = {
    "tool": "you are repeating the same action with the same result.",
    "output": "your recent replies are nearly identical.",
    "input": "you are being shown the same input again and again, however you vary your actions.",
}


class ProgressGuardDetector(Detector):
    """Stall detector. Counts corrections per run; escalates WARN→TRIP after K corrections."""

    name = "progress_guard"

    def __init__(
        self,
        *,
        window: int = 6,
        repeats: int = 3,
        max_corrections: int = 2,
        simhash_threshold: int = 4,
        input_repeats: int = 0,
        input_simhash_threshold: int = 0,
    ) -> None:
        self.input_simhash_threshold = input_simhash_threshold
        self.input_repeats = input_repeats
        self.window = window
        self.repeats = repeats
        self.max_corrections = max_corrections
        self.simhash_threshold = simhash_threshold
        self._corrections: dict[str, int] = defaultdict(int)

    def reset(self, trace_id: str) -> None:
        self._corrections.pop(trace_id, None)

    def _input_stalled(self, step: BoundaryStep, recent: Sequence[BoundaryStep]) -> bool:
        # the same newest message shown to the model again and again
        text = last_message_text(step.input.get("messages"))
        if not text:
            return False
        if self.input_simhash_threshold > 0:  # fuzzy: SimHash within the Hamming threshold
            fp = simhash64(text)

            def match(other: str) -> bool:
                return bool(other) and hamming(simhash64(other), fp) <= self.input_simhash_threshold

        else:  # exact after whitespace collapse
            key = short_hash(text)

            def match(other: str) -> bool:
                return bool(other) and short_hash(other) == key

        same = sum(
            1
            for s in recent
            if s.node_type == "llm" and match(last_message_text(s.input.get("messages")))
        )
        return same >= self.input_repeats

    def _stalled(self, step: BoundaryStep, view: LedgerView, trace_id: str) -> str | None:
        recent = view.recent(trace_id, self.window)
        if step.node_type == "llm" and self.input_repeats > 0 and self._input_stalled(step, recent):
            return "input"
        if step.node_type == "tool" and step.signature and step.result_hash:
            # unchanged RESULT, not merely a repeated call
            same = sum(
                1
                for s in recent
                if s.node_type == "tool"
                and s.signature == step.signature
                and s.result_hash == step.result_hash
            )
            return "tool" if same >= self.repeats else None
        if step.node_type == "llm":
            text = step.output.get("text", "") if isinstance(step.output, dict) else ""
            if not text:
                return None
            fp = simhash64(text)
            near = sum(
                1
                for s in recent
                if s.node_type == "llm"
                and isinstance(s.output, dict)
                and s.output.get("text")
                and hamming(simhash64(s.output["text"]), fp) <= self.simhash_threshold
            )
            return "output" if near >= self.repeats else None
        return None

    def observe(self, attr: Attribution, step: BoundaryStep, view: LedgerView) -> Signal | None:
        kind = self._stalled(step, view, attr.trace_id)
        if kind is None:
            return None
        self._corrections[attr.trace_id] += 1
        corr = self._corrections[attr.trace_id]
        sev = Severity.TRIP if corr > self.max_corrections else Severity.WARN
        return Signal(
            detector=self.name,
            severity=sev,
            trace_id=attr.trace_id,
            reason=f"no progress: {_WHAT[kind]} on '{step.boundary_id}'; correction {corr}",
            evidence={
                "correction": corr,
                "max_corrections": self.max_corrections,
                "kind": kind,
                "boundary_id": step.boundary_id,
                "signature": step.signature,
            },
        )


class ProgressGuardPolicy(Policy):
    name = "progress_guard"

    def decide(self, signal: Signal, view: LedgerView) -> Action:
        if signal.severity is Severity.TRIP:
            return Action(
                kind=ActionKind.HALT,
                trace_id=signal.trace_id,
                reason=f"progress_guard: {signal.evidence['correction']} corrections, no progress, halting",
            )
        return Action(
            kind=ActionKind.INJECT,
            trace_id=signal.trace_id,
            reason=signal.reason,
            inject_message=(
                f"NO PROGRESS DETECTED on '{signal.evidence['boundary_id']}': "
                f"{_NUDGE[str(signal.evidence.get('kind', 'tool'))]} "
                f"Change approach or finalize with what you have."
            ),
        )


def build(
    *,
    window: int = 6,
    repeats: int = 3,
    max_corrections: int = 2,
    simhash_threshold: int = 4,
    input_repeats: int = 0,
    input_simhash_threshold: int = 0,
) -> tuple[Detector, Policy]:
    return (
        ProgressGuardDetector(
            window=window,
            repeats=repeats,
            max_corrections=max_corrections,
            simhash_threshold=simhash_threshold,
            input_repeats=input_repeats,
            input_simhash_threshold=input_simhash_threshold,
        ),
        ProgressGuardPolicy(),
    )
