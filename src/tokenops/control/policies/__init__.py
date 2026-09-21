"""Policy templates — one module per LLD policy row, each a ``(Detector, Policy)`` pair.

Every module exposes a ``build(...) -> tuple[Detector, Policy]`` factory so the config
layer can instantiate templates declaratively and register them with the Governor.

Canonical IDs and display labels are registered in ``control.config.POLICY_TEMPLATES``.
The naming glossary is ``docs/product/policies-index.md``; policy behavior is documented
in ``docs/policies/<id>.md``.

``trajectory_hint`` is known but temporarily disabled in ``build_governor``. Its
standalone module is retained for research/tests and is not exported here.
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
