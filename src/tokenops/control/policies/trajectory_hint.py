"""trajectory_hint — warm-start INJECT from prior successful runs. Opt-in; requires Store.

LLD row:
    Detect: pre_call at step 0; lookup (scope_key, input_hash) with SimHash fallback within
            max_age_days.
    Fix:    INJECT a compressed playbook from the best prior run. Edge-trigger once per run.
            Never HALT.

Index writes are enqueued at run close and built by a background drain worker — not on the
hot path.

**Default: disabled.** Not in ``default.yaml`` or ``_TEMPLATES``; must pass ``enabled: true``
explicitly (e.g. ``steering_trajectory`` bench preset). See ``docs/policies/trajectory_hint.md``.

Bench learnings (Phase 1):
    - Short trajectories: ``min_index_steps`` skips inject when indexed path is too short to
      repay hint overhead (e.g. 2-step example.com → no hint, ~0% cost delta).
    - Tiered ``format_hint``: scale payload by indexed step count; full tier only for long paths.
    - Structural index gates are insufficient: a ``completed`` run can encode a playbook that
      violates task constraints; injecting it can mislead the agent (longer runs, higher cost).
    - Quality / constraint-adherence hook for index writes is Phase 2 — do not expect reliable
      cost savings until then.
    - Live benches: use ``--pause-seconds`` (90s+) between runs to avoid OpenAI TPM 429s.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

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
from tokenops.control.models import RunRegistration
from tokenops.control.trajectory.hint import TrajectoryHit, format_hint, hint_tier_for
from tokenops.control.trajectory.scope import (
    input_hash,
    input_simhash,
    normalize_input,
    scope_key,
    simhash_as_sqlite,
    simhash_from_sqlite,
)

if TYPE_CHECKING:
    from tokenops.control.store import Store


class TrajectoryHintDetector(Detector):
    name = "trajectory_hint"

    def __init__(
        self,
        store: Store,
        *,
        scope_dims: Sequence[str],
        max_age_days: int,
        simhash_threshold: int,
        hint_max_chars: int,
        min_index_steps: int = 4,
        sequence_only_max_steps: int = 6,
        sequence_plus_pitfalls_max_steps: int = 12,
        enabled: bool = True,
    ) -> None:
        self._store = store
        self.scope_dims = list(scope_dims)
        self.max_age_days = max_age_days
        self.simhash_threshold = simhash_threshold
        self.hint_max_chars = hint_max_chars
        self.min_index_steps = min_index_steps
        self.sequence_only_max_steps = sequence_only_max_steps
        self.sequence_plus_pitfalls_max_steps = sequence_plus_pitfalls_max_steps
        self.enabled = enabled
        self._injected: set[str] = set()

    def reset(self, run_id: str) -> None:
        self._injected.discard(run_id)

    def _registration(self, request: CallRequest) -> RunRegistration:
        tags = dict(request.attr.tags)
        intent = tags.pop("intent", "")
        return RunRegistration(
            run_id=request.attr.run_id,
            intent=intent,
            user_dims={k: v for k, v in tags.items() if k != "intent"},
        )

    def _task_text(self, run_id: str) -> str:
        rec = self._store.get_run(run_id)
        if rec and rec.task:
            return rec.task
        return ""

    def pre_call(self, request: CallRequest, view: LedgerView) -> Signal | None:
        if not self.enabled:
            return None
        run_id = request.attr.run_id
        if run_id in self._injected:
            return None
        if not request.primary_agent_turn and view.step_count(run_id) != 0:
            return None
        if view.is_halted(run_id):
            return None

        task = self._task_text(run_id)
        if not task or len(normalize_input(task)) < 10:
            return None

        reg = self._registration(request)
        sk = scope_key(reg, request.attr.agent, self.scope_dims)
        query_hash = input_hash(task)
        query_simhash = input_simhash(task)

        raw = self._store.lookup_trajectory_index(
            scope_key=sk,
            input_hash=query_hash,
            input_simhash=simhash_as_sqlite(query_simhash),
            max_age_days=self.max_age_days,
            simhash_threshold=self.simhash_threshold,
        )
        if raw is None:
            return None

        hit = TrajectoryHit(
            source_run_id=raw["source_run_id"],
            step_count=raw["step_count"],
            cost_micros=raw["cost_micros"],
            tool_sequence=raw["tool_sequence"],
            step_summary=raw["step_summary"],
            match=raw["match"],
        )
        if hit.step_count < self.min_index_steps:
            return None

        tier = hint_tier_for(
            hit.step_count,
            sequence_only_max_steps=self.sequence_only_max_steps,
            sequence_plus_pitfalls_max_steps=self.sequence_plus_pitfalls_max_steps,
        )

        self._injected.add(run_id)
        return Signal(
            detector=self.name,
            severity=Severity.WARN,
            run_id=run_id,
            reason=f"trajectory hint from {hit.source_run_id} ({hit.match} match, tier={tier})",
            evidence={
                "scope_key": sk,
                "source_run_id": hit.source_run_id,
                "step_count": hit.step_count,
                "cost_micros": hit.cost_micros,
                "tool_sequence": hit.tool_sequence,
                "step_summary": hit.step_summary,
                "match": hit.match,
                "hint_tier": tier,
            },
        )


class TrajectoryHintPolicy(Policy):
    name = "trajectory_hint"

    def __init__(
        self,
        *,
        hint_max_chars: int = 1600,
        sequence_only_max_steps: int = 6,
        sequence_plus_pitfalls_max_steps: int = 12,
    ) -> None:
        self.hint_max_chars = hint_max_chars
        self.sequence_only_max_steps = sequence_only_max_steps
        self.sequence_plus_pitfalls_max_steps = sequence_plus_pitfalls_max_steps

    def decide(self, signal: Signal, view: LedgerView) -> Action:
        ev = signal.evidence
        hit = TrajectoryHit(
            source_run_id=str(ev.get("source_run_id", "")),
            step_count=int(ev.get("step_count", 0)),
            cost_micros=int(ev.get("cost_micros", 0)),
            tool_sequence=str(ev.get("tool_sequence", "")),
            step_summary=str(ev.get("step_summary", "")),
            match=str(ev.get("match", "exact")),
        )
        tier = str(ev.get("hint_tier", "full"))
        return Action(
            kind=ActionKind.INJECT,
            run_id=signal.run_id,
            reason=signal.reason,
            inject_message=format_hint(
                hit,
                tier=tier if tier in ("sequence_only", "sequence_plus_pitfalls", "full") else None,
                max_chars=self.hint_max_chars,
                sequence_only_max_steps=self.sequence_only_max_steps,
                sequence_plus_pitfalls_max_steps=self.sequence_plus_pitfalls_max_steps,
            ),
        )


def build(
    store: Store,
    *,
    enabled: bool = False,
    scope_dims: Sequence[str] | None = None,
    max_age_days: int = 30,
    max_entries_per_scope: int = 500,
    simhash_threshold: int = 4,
    min_steps: int = 2,
    min_input_chars: int = 10,
    min_index_steps: int = 4,
    sequence_only_max_steps: int = 6,
    sequence_plus_pitfalls_max_steps: int = 12,
    hint_max_chars: int = 1600,
    require_scope: bool = False,
) -> tuple[Detector, Policy]:
    if max_age_days <= 0:
        raise ValueError("trajectory_hint.max_age_days is required and must be > 0")
    dims = list(scope_dims or ["intent", "agent"])
    detector = TrajectoryHintDetector(
        store,
        scope_dims=dims,
        max_age_days=max_age_days,
        simhash_threshold=simhash_threshold,
        hint_max_chars=hint_max_chars,
        min_index_steps=min_index_steps,
        sequence_only_max_steps=sequence_only_max_steps,
        sequence_plus_pitfalls_max_steps=sequence_plus_pitfalls_max_steps,
        enabled=enabled,
    )
    policy = TrajectoryHintPolicy(
        hint_max_chars=hint_max_chars,
        sequence_only_max_steps=sequence_only_max_steps,
        sequence_plus_pitfalls_max_steps=sequence_plus_pitfalls_max_steps,
    )
    detector._index_params = {  # type: ignore[attr-defined]
        "enabled": enabled,
        "scope_dims": dims,
        "max_age_days": max_age_days,
        "max_entries_per_scope": max_entries_per_scope,
        "simhash_threshold": simhash_threshold,
        "min_steps": min_steps,
        "min_input_chars": min_input_chars,
        "min_index_steps": min_index_steps,
        "sequence_only_max_steps": sequence_only_max_steps,
        "sequence_plus_pitfalls_max_steps": sequence_plus_pitfalls_max_steps,
        "require_scope": require_scope,
        "hint_max_chars": hint_max_chars,
    }
    return detector, policy
