"""TokenOps integration over the Chronicle package.

Uses ``chronicle`` from https://github.com/theagentplane/chronicle for
record/replay. TokenOps adds governance projection via ``boundary`` in
``tokenops.chronicle.boundary``.
"""

from chronicle.envelope.schema import (
    ActionResult,
    Envelope,
    InputState,
    ToolCall,
)
from chronicle.replay.plan import BoundaryMode, ReplayPlan
from chronicle.session import (
    ChronicleSession,
    SessionMode,
    get_session,
    reset_session,
)

from tokenops.chronicle.boundary import boundary

# Backward-compatible alias (pre-coupling in-memory envelope type).
RecordedEnvelope = Envelope

# Upstream keeps envelopes on a private field; expose a read-only view.
if not hasattr(ChronicleSession, "recorded_envelopes"):

    @property  # type: ignore[misc]
    def recorded_envelopes(self) -> list[Envelope]:
        return list(self._recorded_envelopes)

    ChronicleSession.recorded_envelopes = recorded_envelopes  # type: ignore[attr-defined]

__all__ = [
    "ActionResult",
    "BoundaryMode",
    "ChronicleSession",
    "Envelope",
    "InputState",
    "RecordedEnvelope",
    "ReplayPlan",
    "SessionMode",
    "ToolCall",
    "boundary",
    "get_session",
    "reset_session",
]
