"""TokenOps control layer (v1).

The Account (ledger) + Enforce (policies) half of the control plane. Consumes
attributed boundary crossings, records them, and decides: steer or stop.

Built-in IDs and display labels live in ``config.POLICY_TEMPLATES``; see the single
glossary at ``docs/product/policies-index.md`` and behavior docs at ``docs/policies/``.
``core.py`` is the canonical runtime vocabulary.
"""

from tokenops.control.attribution import (
    merge_hop_dims,
    merge_registration_dims,
    require_hop,
    require_registration,
)
from tokenops.control.boundary import emit_observation, observation_from_crossing
from tokenops.control.config import build_governance_stack, build_governor
from tokenops.control.context import (
    GovernanceContext,
    SpanContext,
)
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
from tokenops.control.crossing import install_crossing_hook, on_crossing
from tokenops.control.engine import (
    AgentControls,
    ApplyControls,
    Governor,
    PreviewControls,
    RaiseControls,
    Throttled,
    governance_events_payload,
    halt_detector_from_events,
)
from tokenops.control.integration import (
    apply_carry_to_messages,
    consume_carry,
    make_on_step,
    step_to_observation,
    wrap_complete,
    wrap_stream,
)
from tokenops.control.ledger import Budget, Ledger, LocalRunState, segment_key
from tokenops.repositories import (
    ApplyResult,
    ControlPlaneClient,
    LedgerEvent,
    PrecheckRequest,
    PrecheckResult,
)

# Process-wide: register the governor hook on chronicle.default_hooks (inherited by every session).
install_crossing_hook()

from tokenops.control.http import with_governance_errors
from tokenops.control.instrument import instrument_app
from tokenops.control.ledger_writers import flush_ledger_writes
from tokenops.control.models import (
    GovernanceMode,
    HopAttribution,
    NoGovernanceScopeError,
    RunNotRegisteredError,
    RunRegistration,
    parse_governance_mode,
)
from tokenops.control.request_context import (
    RequestContext,
    bind_request_context,
    clear_request_context,
    current_request_context,
)
from tokenops.control.run import TokenOpsBound, agentplane_run_scope, tokenops_run

__all__ = [
    # vocabulary
    "Action",
    "ActionKind",
    "Attribution",
    "BoundaryStep",
    "CallRequest",
    "Detector",
    "Halt",
    "LedgerView",
    "Observation",
    "Policy",
    "Severity",
    "Signal",
    "Usage",
    # ledger
    "Budget",
    "Ledger",
    "LocalRunState",
    "segment_key",
    # control plane client types
    "ControlPlaneClient",
    "LedgerEvent",
    "PrecheckRequest",
    "PrecheckResult",
    "ApplyResult",
    # harness
    "Governor",
    "RaiseControls",
    "AgentControls",
    "ApplyControls",
    "PreviewControls",
    "Throttled",
    "governance_events_payload",
    "halt_detector_from_events",
    # config factory
    "build_governor",
    "build_governance_stack",
    # data-plane integration
    "make_on_step",
    "wrap_complete",
    "wrap_stream",
    "apply_carry_to_messages",
    "consume_carry",
    "step_to_observation",
    # attribution / unified run
    "HopAttribution",
    "NoGovernanceScopeError",
    "RunNotRegisteredError",  # deprecated alias
    "RunRegistration",  # deprecated alias
    "GovernanceMode",
    "parse_governance_mode",
    "merge_hop_dims",
    "require_hop",
    "merge_registration_dims",  # deprecated alias
    "require_registration",  # deprecated alias
    "tokenops_run",
    "agentplane_run_scope",
    "TokenOpsBound",
    "RequestContext",
    "bind_request_context",
    "clear_request_context",
    "current_request_context",
    "instrument_app",
    "flush_ledger_writes",
    "SpanContext",
    "GovernanceContext",
    "observation_from_crossing",
    "emit_observation",
    # Chronicle crossing hook
    "install_crossing_hook",
    "on_crossing",
    # HTTP
    "with_governance_errors",
]
