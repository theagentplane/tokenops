"""output_runaway — heals, never halts. Default; backstops own any stop.

LLD row:
    Detect: n-gram repetition over the streamed visible output (repeats ≥ R, single-token
            domination, or tail-loop). Prevent most by setting frequency/presence penalties +
            a max_output cap on the original request.
    Fix:    CANCEL the stream (hard-break) to stop the bleed; RETRY bounded with raised
            frequency/presence penalties, a tighter cap, and optional logit_bias on the
            looping tokens; if still degenerate after the bounded retries, INJECT a
            "generation degenerated" error to the agent and continue. No HALT — persistent
            failure is caught by cost_budget / step_cap / progress_guard.

Outputs shorter than ``min_words`` are never flagged. With only a few words the most common
word is always a large share of the text (with two words it is at least half), so the
domination signal carries no information there, and a retry re-sends the whole prompt, so
it costs more than any short output it could replace. Structured agents hit this every
step: browser-use's compact action JSON (``{"action":[{"click":{"index":3}}]}``) is a
single whitespace-separated word.

This observe-path detector runs on the completed visible text. In a true streaming wrap the
first action is CANCEL (stop mid-stream); here the stream has finished, so the policy goes
straight to bounded RETRY, then INJECT. Never HALT.
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
from tokenops.framework.policies._util import max_ngram_repeat, single_token_domination


class OutputRunawayDetector(Detector):
    """WARN when the visible output is degenerate (n-gram loop or single-token domination)."""

    name = "output_runaway"

    def __init__(
        self, *, n: int = 3, repeats: int = 4, domination: float = 0.5, min_words: int = 12
    ) -> None:
        self.n = n
        self.repeats = repeats
        self.domination = domination
        self.min_words = min_words

    def observe(self, attr: Attribution, step: BoundaryStep, view: LedgerView) -> Signal | None:
        if step.node_type != "llm" or not isinstance(step.output, dict):
            return None
        text = step.output.get("text", "")
        if not text or len(text.split()) < self.min_words:
            return None
        rep = max_ngram_repeat(text, self.n)
        dom = single_token_domination(text)
        if rep >= self.repeats or dom >= self.domination:
            return Signal(
                detector=self.name,
                severity=Severity.WARN,
                trace_id=attr.trace_id,
                reason=f"degenerate output: ngram x{rep}, domination {dom:.0%}",
                evidence={"ngram_repeat": rep, "domination": dom},
            )
        return None


class OutputRunawayPolicy(Policy):
    """Bounded RETRY with raised penalties / tighter cap; after the bound, INJECT an error
    and continue. Never HALT — the breaker backstops own any hard stop."""

    name = "output_runaway"

    def __init__(self, *, max_retries: int = 2) -> None:
        self.max_retries = max_retries
        self._retries: dict[str, int] = defaultdict(int)

    def reset(self, trace_id: str) -> None:
        self._retries.pop(trace_id, None)

    def decide(self, signal: Signal, view: LedgerView) -> Action:
        n = self._retries[signal.trace_id]
        if n < self.max_retries:
            self._retries[signal.trace_id] += 1
            return Action(
                kind=ActionKind.RETRY,
                trace_id=signal.trace_id,
                reason=f"retry {n + 1}/{self.max_retries}: raise frequency/presence penalties, "
                f"tighten max_output, logit_bias on looping tokens",
            )
        return Action(
            kind=ActionKind.INJECT,
            trace_id=signal.trace_id,
            reason=signal.reason,
            inject_message="ERROR: generation degenerated (repetition) after bounded retries; "
            "proceed without this output.",
        )


def build(
    *,
    n: int = 3,
    repeats: int = 4,
    domination: float = 0.5,
    max_retries: int = 2,
    min_words: int = 12,
) -> tuple[Detector, Policy]:
    detector = OutputRunawayDetector(
        n=n, repeats=repeats, domination=domination, min_words=min_words
    )
    return detector, OutputRunawayPolicy(max_retries=max_retries)
