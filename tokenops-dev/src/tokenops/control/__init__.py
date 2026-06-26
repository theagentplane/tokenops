"""TokenOps control layer (v1).

The Account (ledger) + Enforce (policies) half of the control plane. Consumes
attributed boundary crossings, records them, and decides: steer or stop.

Ten policies (delegation_cap dropped — fan-out is concurrency_cap, spend is
cost_budget / pre_call_worst_case), evaluated by moment:
  pre_call : concurrency_cap, tool_fix, context_compaction, cost_guard, pre_call_worst_case
  stream   : output_runaway
  observe  : cost_budget, step_cap, tool_output_cap, progress_guard

Source of truth: tokenops-lld/tokenops-policies-lld.md. The ``contract/`` folder was
the design draft; ``core.py`` here is the promoted, canonical vocabulary.
"""

from tokenops.control.core import (
    Action,
    ActionKind,
    Attribution,
    BoundaryStep,
    CallRequest,
    Detector,
    Halt,
    LedgerView,
    Observation,
    Policy,
    Severity,
    Signal,
    Usage,
)
from tokenops.control.config import build_governor
from tokenops.control.engine import AgentControls, ApplyControls, Governor, RaiseControls, Throttled
from tokenops.control.integration import make_on_step, wrap_complete
from tokenops.control.ledger import Budget, Ledger, RunState, segment_key

__all__ = [
    # vocabulary
    "Action", "ActionKind", "Attribution", "BoundaryStep", "CallRequest",
    "Detector", "Halt", "LedgerView", "Observation", "Policy", "Severity",
    "Signal", "Usage",
    # ledger
    "Budget", "Ledger", "RunState", "segment_key",
    # harness
    "Governor", "RaiseControls", "AgentControls", "ApplyControls", "Throttled",
    # config factory
    "build_governor",
    # data-plane integration
    "make_on_step", "wrap_complete",
]
