"""Structural eligibility gates for trajectory index writes.

Phase 1: completed / min-steps / min-input only. Quality or constraint-adherence scoring
is Phase 2 — see docs/policies/trajectory_hint.md.
"""

from __future__ import annotations

from tokenops.control.models import RunRecord
from tokenops.control.trajectory.scope import normalize_input


def structural_index_eligible(
    rec: RunRecord,
    *,
    min_steps: int = 2,
    min_input_chars: int = 10,
    require_scope: bool = False,
    scope_has_none: bool = False,
) -> bool:
    """True when a completed run may be enqueued for background indexing."""
    if rec.status != "completed":
        return False
    if rec.halt_reason:
        return False
    if rec.steps < min_steps:
        return False
    if rec.cost_micros <= 0:
        return False
    task = normalize_input(rec.task or "")
    if not task or len(task) < min_input_chars:
        return False
    if require_scope and scope_has_none:
        return False
    return True
