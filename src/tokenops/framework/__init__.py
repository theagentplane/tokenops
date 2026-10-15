"""The framework layer: in-process machinery, with no network.

Policies, pricing, the ledger, the governor and the vocabulary they share. Everything that
talks to the control plane lives in :mod:`tokenops.repositories`; this layer only sees it
through the :class:`~tokenops.framework.ledger_backend.LedgerBackend` and
:class:`~tokenops.framework.ledger_backend.LedgerWriter` protocols.

Built-in policy IDs and display labels live in ``config.POLICY_TEMPLATES``; see the glossary at
``docs/product/policies-index.md`` and behaviour docs at ``docs/policies/``. ``core.py`` is the
runtime vocabulary.
"""

from tokenops.framework.attribution import (
    merge_hop_dims,
    require_hop,
)
from tokenops.framework.boundary import emit_observation, observation_from_crossing
from tokenops.framework.config import build_governance_stack, build_governor
from tokenops.framework.context import GovernanceContext, SpanContext
from tokenops.framework.core import (
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
from tokenops.framework.engine import (
    AgentControls,
    ApplyControls,
    Governor,
    PreviewControls,
    RaiseControls,
    Throttled,
    governance_events_payload,
    halt_detector_from_events,
)
from tokenops.framework.ledger import Budget, Ledger, LocalRunState, segment_key
from tokenops.framework.ledger_backend import LedgerBackend, LedgerWriter
from tokenops.framework.ledger_types import (
    ApplyResult,
    LedgerEvent,
    PrecheckRequest,
    PrecheckResult,
)
from tokenops.framework.models import (
    GovernanceMode,
    HopAttribution,
    NoGovernanceScopeError,
    parse_governance_mode,
)
from tokenops.framework.request_context import (
    RequestContext,
    bind_request_context,
    clear_request_context,
    current_request_context,
)

__all__ = [
    "Action",
    "ActionKind",
    "AgentControls",
    "ApplyControls",
    "ApplyResult",
    "Attribution",
    "BoundaryStep",
    "Budget",
    "CallRequest",
    "Detector",
    "GovernanceContext",
    "GovernanceMode",
    "Governor",
    "Halt",
    "HopAttribution",
    "Ledger",
    "LedgerBackend",
    "LedgerEvent",
    "LedgerView",
    "LedgerWriter",
    "LocalRunState",
    "NoGovernanceScopeError",
    "Observation",
    "Policy",
    "PrecheckRequest",
    "PrecheckResult",
    "PreviewControls",
    "RaiseControls",
    "RequestContext",
    "Severity",
    "Signal",
    "SpanContext",
    "Throttled",
    "Usage",
    "bind_request_context",
    "build_governance_stack",
    "build_governor",
    "clear_request_context",
    "current_request_context",
    "emit_observation",
    "governance_events_payload",
    "halt_detector_from_events",
    "merge_hop_dims",
    "observation_from_crossing",
    "parse_governance_mode",
    "require_hop",
    "segment_key",
]
