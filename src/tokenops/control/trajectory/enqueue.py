"""Run-close enqueue for trajectory index background build."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping, Sequence

from tokenops.control.core import BoundaryStep
from tokenops.control.models import RunRecord, RunRegistration
from tokenops.control.trajectory.gates import structural_index_eligible
from tokenops.control.trajectory.scope import input_hash, input_simhash, normalize_input, scope_key, simhash_as_sqlite
from tokenops.control.trajectory.serialize import window_to_json

if TYPE_CHECKING:
    from tokenops.control.store import Store


def _scope_has_none(registration: RunRegistration, scope_dims: Sequence[str], agent: str) -> bool:
    key = scope_key(registration, agent, scope_dims)
    return "_none" in key


def enqueue_completed_run(
    store: "Store",
    *,
    rec: RunRecord,
    registration: RunRegistration,
    agent: str,
    window: Sequence[BoundaryStep],
    policy_params: Mapping[str, Any] | None,
) -> bool:
    """Persist a window snapshot and enqueue a background index build. Returns True if enqueued."""
    params = dict(policy_params or {})
    if not params.get("enabled", False):
        return False

    scope_dims = params.get("scope_dims") or ["intent", "agent"]
    min_steps = int(params.get("min_steps", 2))
    min_input_chars = int(params.get("min_input_chars", 10))

    if not structural_index_eligible(
        rec,
        min_steps=min_steps,
        min_input_chars=min_input_chars,
        require_scope=bool(params.get("require_scope", False)),
        scope_has_none=_scope_has_none(registration, scope_dims, agent),
    ):
        return False

    task = rec.task or ""
    norm = normalize_input(task)
    sk = scope_key(registration, agent, scope_dims)

    store.save_trajectory_snapshot(rec.run_id, window_to_json(window))
    store.enqueue_trajectory_build(
        run_id=rec.run_id,
        scope_key=sk,
        input_hash=input_hash(task),
        input_simhash=simhash_as_sqlite(input_simhash(task)),
        input_preview=norm[:120],
        task_text=task,
        cost_micros=rec.cost_micros,
        step_count=rec.steps,
    )
    return True
