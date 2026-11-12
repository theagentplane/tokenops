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

Three inputs, all deterministic:

* **Repeated result** (built in): an unchanged (signature, result_hash) on a tool, or a
  near-duplicate llm output.
* **Domain progress signal** (from the adapter, ``tags["progress"]``): ``"no"`` when the agent
  itself reports that a step did not work, ``"yes"`` when it did. ``progress_streak``
  consecutive ``"no"`` count as a stall. A self-report is used instead of the repeated-result
  rule because three "worked" reports in a row would otherwise read as a stall.
* **Blocked page** (from the adapter, ``tags["blocked"] == "yes"``): a bot-check or captcha
  page. Every blocked step is a stall: no action on that page can make progress.

**Corrections reset on progress** (``reset_on_progress``, default on): when the boundary that
stalled next shows a changed result, or the agent reports ``progress == "yes"``, the count
starts again, so two unrelated stalls far apart do not add up to a halt. Set it to ``False``
for the count to last the whole run (the behaviour before this change).

**Wrap-up before halt** (``wrap_up``, off by default): where the policy would HALT, it first
sends one "finish now with your best answer" message, and halts on the next stall. A halted
run of an answer-producing agent (a browser agent) scores zero even when it already holds a
partial answer. The halt is still decided by a stall; the HALT action itself is unchanged.

**Grace period** (``grace_steps``, default 0): no correction before the run's
``grace_steps``-th boundary step, except on a blocked page. Early in a run a failed step is
often just the agent finding its way, and an early "no progress" message can keep an agent
trying on a task it was about to give up on (a longer, more expensive failure).

An adapter that sends no tags gets exactly the repeated-result behaviour.
"""

from __future__ import annotations

from collections import defaultdict

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
from tokenops.framework.policies._util import hamming, simhash64

#: Tag names an adapter sets on an observation (``Observation.tags`` / ``extra_tags``).
PROGRESS_TAG = "progress"
BLOCKED_TAG = "blocked"


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
        progress_streak: int = 3,
        reset_on_progress: bool = True,
        wrap_up: bool = False,
        grace_steps: int = 0,
    ) -> None:
        self.wrap_up = wrap_up
        self.grace_steps = grace_steps
        self.window = window
        self.repeats = repeats
        self.max_corrections = max_corrections
        self.simhash_threshold = simhash_threshold
        self.progress_streak = progress_streak
        self.reset_on_progress = reset_on_progress
        self._corrections: dict[str, int] = defaultdict(int)
        self._no_progress: dict[str, int] = defaultdict(int)
        self._stalled_at: dict[str, str] = {}  # trace -> boundary of the last stall

    def reset(self, trace_id: str) -> None:
        self._corrections.pop(trace_id, None)
        self._no_progress.pop(trace_id, None)
        self._stalled_at.pop(trace_id, None)

    def _repeated(self, step: BoundaryStep, view: LedgerView, trace_id: str) -> bool:
        recent = view.recent(trace_id, self.window)
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

    def _progressed(self, trace_id: str) -> None:
        if self.reset_on_progress:
            self._corrections.pop(trace_id, None)
            self._stalled_at.pop(trace_id, None)

    def _cause(self, step: BoundaryStep, view: LedgerView, trace_id: str) -> str | None:
        """Why this step is a stall (``blocked`` / ``no_progress`` / ``repeated``), or None."""
        if step.tags.get(BLOCKED_TAG) == "yes":
            return "blocked"
        progress = step.tags.get(PROGRESS_TAG)
        early = step.step < self.grace_steps
        if progress == "no":
            self._no_progress[trace_id] += 1
            if self._no_progress[trace_id] >= self.progress_streak and not early:
                self._no_progress[trace_id] = 0  # a fresh streak before the next correction
                return "no_progress"
            return None
        if progress == "yes":
            self._no_progress[trace_id] = 0
            self._progressed(trace_id)
            return None
        if not early and self._repeated(step, view, trace_id):
            return "repeated"
        if self._stalled_at.get(trace_id) == step.boundary_id:
            self._progressed(trace_id)  # the boundary that stalled has moved on
        return None

    def observe(self, attr: Attribution, step: BoundaryStep, view: LedgerView) -> Signal | None:
        cause = self._cause(step, view, attr.trace_id)
        if cause is None:
            return None
        self._corrections[attr.trace_id] += 1
        self._stalled_at[attr.trace_id] = step.boundary_id
        corr = self._corrections[attr.trace_id]
        sev = Severity.TRIP if corr > self.max_corrections else Severity.WARN
        if sev is Severity.TRIP and self.wrap_up and corr == self.max_corrections + 1:
            sev, cause = Severity.WARN, "wrap_up"  # one last message before the halt
        what = {
            "blocked": "the page is a bot check",
            "no_progress": f"{self.progress_streak} steps in a row reported as not working",
            "repeated": "repeated result",
            "wrap_up": "still no progress after corrections, asking for the final answer",
        }[cause]
        return Signal(
            detector=self.name,
            severity=sev,
            trace_id=attr.trace_id,
            reason=f"no progress: {what} on '{step.boundary_id}'; correction {corr}",
            evidence={
                "correction": corr,
                "max_corrections": self.max_corrections,
                "boundary_id": step.boundary_id,
                "signature": step.signature,
                "cause": cause,
            },
        )


_MESSAGES = {
    "blocked": "BLOCKED: this site is showing a bot check and will not let you continue. Use "
    "another source for the information, or finish now with the best answer you have.",
    "no_progress": "NO PROGRESS: your last steps did not work. Unless another approach is clearly "
    "available, finish now with the best answer you have.",
    "wrap_up": "FINAL STEP: you are not making progress and this run is about to be stopped. "
    "Finish now with the best answer you have.",
}


class ProgressGuardPolicy(Policy):
    name = "progress_guard"

    def decide(self, signal: Signal, view: LedgerView) -> Action:
        if signal.severity is Severity.TRIP:
            return Action(
                kind=ActionKind.HALT,
                trace_id=signal.trace_id,
                reason=f"progress_guard: {signal.evidence['correction']} corrections, no progress, halting",
            )
        message = _MESSAGES.get(
            str(signal.evidence.get("cause", "repeated")),
            f"NO PROGRESS DETECTED on '{signal.evidence['boundary_id']}': you are repeating "
            f"the same action with the same result. Change approach or finalize with what you have.",
        )
        return Action(
            kind=ActionKind.INJECT,
            trace_id=signal.trace_id,
            reason=signal.reason,
            inject_message=message,
        )


def build(
    *,
    window: int = 6,
    repeats: int = 3,
    max_corrections: int = 2,
    simhash_threshold: int = 4,
    progress_streak: int = 3,
    reset_on_progress: bool = True,
    wrap_up: bool = False,
    grace_steps: int = 0,
) -> tuple[Detector, Policy]:
    return (
        ProgressGuardDetector(
            window=window,
            repeats=repeats,
            max_corrections=max_corrections,
            simhash_threshold=simhash_threshold,
            progress_streak=progress_streak,
            reset_on_progress=reset_on_progress,
            wrap_up=wrap_up,
            grace_steps=grace_steps,
        ),
        ProgressGuardPolicy(),
    )
