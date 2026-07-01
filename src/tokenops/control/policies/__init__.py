"""Policy templates — one module per LLD policy row, each a ``(Detector, Policy)`` pair.

Every module exposes a ``build(...) -> tuple[Detector, Policy]`` factory so the config
layer can instantiate templates declaratively and register them with the Governor.

Governance docs (the action each policy takes) live in ``tokenops-lld/policies/``.
"""

from tokenops.control.policies import (
    concurrency_cap,
    context_compaction,
    cost_budget,
    cost_guard,
    output_runaway,
    pre_call_worst_case,
    progress_guard,
    step_cap,
    tool_fix,
    tool_output_cap,
)

__all__ = [
    "concurrency_cap",
    "context_compaction",
    "cost_budget",
    "cost_guard",
    "output_runaway",
    "pre_call_worst_case",
    "progress_guard",
    "step_cap",
    "tool_fix",
    "tool_output_cap",
]
