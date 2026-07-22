"""Three-agent TokenOps bench: Planner → Researcher → Writer.

Agent logic in ``agent.py`` is intentionally vanilla (naive). TokenOps seams
live in each ``server.py`` (entry/downstream run scope / governance_scope /
wrap_complete / @boundary / crossing hook / span-propagated hops).
"""

from examples.triad.client import submit_goal_sync, submit_goal_sync_with_meta

__all__ = ["submit_goal_sync", "submit_goal_sync_with_meta"]
