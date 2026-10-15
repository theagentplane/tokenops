"""In-process vocabulary shared by the run scope and the governors.

Plain data only. The control plane owns configuration storage (segments, budgets, policy
instances) and the trace list; nothing here is persisted by TokenOps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

Dimension = Literal["trace", "user", "agent", "tenant", "tag"]


class GovernanceMode(str, Enum):
    ENFORCE = "enforce"
    PREVIEW = "preview"


def parse_governance_mode(value: object) -> GovernanceMode:
    """Parse API / config values into :class:`GovernanceMode`."""
    if value is None or value == "":
        return GovernanceMode.ENFORCE
    if isinstance(value, GovernanceMode):
        return value
    key = str(value).strip().lower()
    for mode in GovernanceMode:
        if key == mode.value:
            return mode
    raise ValueError(f"unknown governance mode: {value!r}")


@dataclass(frozen=True, kw_only=True)
class RunRegistration:
    """The attribution of one hop under a trace: who, why and in which mode.

    Built in memory by ``tokenops_run`` from the Chronicle trace id and the hop's own
    ``intent`` / ``user_dims`` / ``mode``. Nothing is registered with, or persisted by, the
    control plane: a run is a Chronicle trace.
    """

    trace_id: str
    intent: str = ""
    user_dims: dict[str, str] = field(default_factory=dict)
    mode: GovernanceMode = GovernanceMode.ENFORCE


class RunNotRegisteredError(LookupError):
    """Telemetry was produced outside a bound ``tokenops_run`` scope."""
