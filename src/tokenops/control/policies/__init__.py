"""Policy templates — one module per LLD policy row, each a ``(Detector, Policy)`` pair.

Every module exposes a ``build(...) -> tuple[Detector, Policy]`` factory so the config
layer can instantiate templates declaratively and register them with the Governor.

Canonical IDs and display labels are registered in ``control.config.POLICY_TEMPLATES``.
The naming glossary is ``docs/product/policies-index.md``; policy behavior is documented
in ``docs/policies/<id>.md``.

State each policy reads (ADR 0004):

=====================  ==========================================================
Policy                 Reads
=====================  ==========================================================
cost_budget            plane: spend of its budget (``precheck``)
pre_call_worst_case    plane: spend of its budget (``precheck``)
cost_guard             plane: spend; in process: velocity from the step window
concurrency_cap        plane: in-flight count of its segment (``precheck``)
step_cap               in process: this process's step count for the trace
progress_guard         in process: the recent step window
context_compaction     in process: the recent step window
output_runaway         the current call's output only
tool_fix               the current call's tool request only
tool_output_cap        the current call's tool output only
time_budget            the wall clock since the hop started
=====================  ==========================================================

``trajectory_hint`` (a cross-run playbook hint) was removed in 1.0.1; see ADR 0005.
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
    time_budget,
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
    "time_budget",
    "tool_fix",
    "tool_output_cap",
]
