"""Three-agent TokenOps bench: Planner → Researcher → Writer.

Agent logic in ``agent.py`` is intentionally vanilla (naive). TokenOps seams
live in each ``server.py`` (register_run / governance_scope / wrap_complete /
@boundary / crossing hook / delegate rollup).
"""

from bench.triad.client import submit_goal_sync, submit_goal_sync_with_meta

__all__ = ["submit_goal_sync", "submit_goal_sync_with_meta"]
