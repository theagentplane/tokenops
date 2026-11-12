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

**Unchanged input** (``input_repeats`` > 0, off by default): the newest message sent to the
model is the same text (exact, or SimHash within ``input_simhash_threshold`` when > 0) on at
least ``input_repeats`` calls in the window, whatever the model replies or does. It catches an
agent that varies its actions but is shown the same screen every time.

An adapter that sends no tags gets exactly the repeated-result behaviour.
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
    "blocked": "the page is a bot check",
    "wrap_up": "still no progress after corrections, asking for the final answer",
}
_NUDGE = {
    "tool": "you are repeating the same action with the same result.",
    "output": "your recent replies are nearly identical.",
    "input": "you are being shown the same input again and again, however you vary your actions.",
}


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
        input_repeats: int = 0,
        input_simhash_threshold: int = 0,
    ) -> None:
        self.input_simhash_threshold = input_simhash_threshold
        self.input_repeats = input_repeats
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

    def _progressed(self, trace_id: str) -> None:
        if self.reset_on_progress:
            self._corrections.pop(trace_id, None)
            self._stalled_at.pop(trace_id, None)

    def _cause(self, step: BoundaryStep, view: LedgerView, trace_id: str) -> str | None:
        """Why this step is a stall (``blocked`` / ``no_progress`` / ``tool`` / ``output`` / ``input``), or None."""
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
        kind = None if early else self._stalled(step, view, trace_id)
        if kind is not None:
            return kind  # "tool", "output" or "input"
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
        what = (
            f"{self.progress_streak} steps in a row reported as not working"
            if cause == "no_progress"
            else _WHAT[cause]
        )
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
                "kind": cause,
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
        cause = str(signal.evidence.get("cause") or signal.evidence.get("kind") or "tool")
        message = _MESSAGES.get(cause) or (
            f"NO PROGRESS DETECTED on '{signal.evidence['boundary_id']}': "
            f"{_NUDGE.get(cause, _NUDGE['tool'])} "
            f"Change approach or finalize with what you have."
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
    input_repeats: int = 0,
    input_simhash_threshold: int = 0,
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
            input_repeats=input_repeats,
            input_simhash_threshold=input_simhash_threshold,
        ),
        ProgressGuardPolicy(),
    )
