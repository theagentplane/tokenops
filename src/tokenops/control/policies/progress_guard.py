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
from tokenops.control.policies._util import hamming, simhash64


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
    ) -> None:
        self.window = window
        self.repeats = repeats
        self.max_corrections = max_corrections
        self.simhash_threshold = simhash_threshold
        self._corrections: dict[str, int] = defaultdict(int)

    def reset(self, run_id: str) -> None:
        self._corrections.pop(run_id, None)

    def _stalled(self, step: BoundaryStep, view: LedgerView, run_id: str) -> bool:
        recent = view.recent(run_id, self.window)
        if step.node_type == "tool" and step.signature and step.result_hash:
            # unchanged RESULT, not merely a repeated call
            same = sum(
                1
                for s in recent
                if s.node_type == "tool"
                and s.signature == step.signature
                and s.result_hash == step.result_hash
            )
            return same >= self.repeats
        if step.node_type == "llm":
            text = step.output.get("text", "") if isinstance(step.output, dict) else ""
            if not text:
                return False
            fp = simhash64(text)
            near = sum(
                1
                for s in recent
                if s.node_type == "llm"
                and isinstance(s.output, dict)
                and s.output.get("text")
                and hamming(simhash64(s.output["text"]), fp) <= self.simhash_threshold
            )
            return near >= self.repeats
        return False

    def observe(self, attr: Attribution, step: BoundaryStep, view: LedgerView) -> Signal | None:
        if not self._stalled(step, view, attr.run_id):
            return None
        self._corrections[attr.run_id] += 1
        corr = self._corrections[attr.run_id]
        sev = Severity.TRIP if corr > self.max_corrections else Severity.WARN
        return Signal(
            detector=self.name,
            severity=sev,
            run_id=attr.run_id,
            reason=f"no progress: repeated result on '{step.boundary_id}'; correction {corr}",
            evidence={
                "correction": corr,
                "max_corrections": self.max_corrections,
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
                run_id=signal.run_id,
                reason=f"progress_guard: {signal.evidence['correction']} corrections, no progress — halting",
            )
        return Action(
            kind=ActionKind.INJECT,
            run_id=signal.run_id,
            reason=signal.reason,
            inject_message=(
                f"NO PROGRESS DETECTED on '{signal.evidence['boundary_id']}': you are repeating "
                f"the same action with the same result. Change approach or finalize with what you have."
            ),
        )


def build(
    *, window: int = 6, repeats: int = 3, max_corrections: int = 2, simhash_threshold: int = 4
) -> tuple[Detector, Policy]:
    return (
        ProgressGuardDetector(
            window=window,
            repeats=repeats,
            max_corrections=max_corrections,
            simhash_threshold=simhash_threshold,
        ),
        ProgressGuardPolicy(),
    )
