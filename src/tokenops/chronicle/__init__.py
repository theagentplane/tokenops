"""Chronicle-compatible boundary instrumentation (+ TokenOps govern projection).

Mirrors `chronicle` from https://github.com/theagentplane/chronicle — same
``@boundary`` / session / replay API. TokenOps adds ``governor.observe`` when
governance context is bound (see ``tokenops.control.context.governance_scope``).
"""

from tokenops.chronicle.boundary import boundary
from tokenops.chronicle.replay import BoundaryMode, ReplayPlan
from tokenops.chronicle.session import (
    ChronicleSession,
    SessionMode,
    get_session,
    reset_session,
)

__all__ = [
    "boundary",
    "ReplayPlan",
    "BoundaryMode",
    "ChronicleSession",
    "SessionMode",
    "get_session",
    "reset_session",
]
