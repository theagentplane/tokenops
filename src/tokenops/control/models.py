"""Persisted models for the admin store (goal 3) and the run dashboard (goal 4).

Plain dataclasses — the storage shape, kept separate from the runtime vocabulary in
``core.py``/``ledger.py``. The store (``store.py``) turns rows into these and back, and
assembles ``governance_config_for(agent)`` into the exact dict ``build_governor`` consumes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Dimension = Literal["run", "user", "agent", "tenant", "tag"]
RunStatus = Literal["running", "completed", "halted", "throttled", "error"]


@dataclass(frozen=True, kw_only=True)
class RunRegistration:
    """Frozen trace dims registered before any telemetry for a ``run_id``.

    See ``docs/run-attribution.md``. Registration is required and immutable for
    the life of the run.
    """

    run_id: str
    intent: str = ""
    user_dims: dict[str, str] = field(default_factory=dict)


class RunNotRegisteredError(LookupError):
    """Telemetry references a ``run_id`` that was never registered."""


class RunAlreadyRegisteredError(ValueError):
    """``register_run`` was called twice for the same ``run_id``."""


@dataclass
class Segment:
    """A named, reusable matcher — generalizes ``Budget.dimension/tag_key`` into a thing a
    user can create once and attach to budgets/policies."""

    id: str
    name: str
    dimension: Dimension = "run"
    tag_key: str | None = None
    match_value: str | None = None  # for a tag segment, the value to match (optional)


@dataclass
class BudgetSpec:
    """A persisted ``ledger.Budget``. ``limit_micros=None`` means unlimited (accumulator only)."""

    id: str
    limit_micros: int | None
    dimension: Dimension = "run"
    tag_key: str | None = None
    period: str = "lifetime"


@dataclass
class PolicyInstance:
    """One configured policy = a template + params, optionally scoped to an agent and
    attached to a budget and/or segment."""

    id: str
    template: str               # a key of control.config._TEMPLATES
    params: dict[str, Any] = field(default_factory=dict)
    agent: str | None = None    # None = applies to every agent
    budget_id: str | None = None
    segment_id: str | None = None
    enabled: bool = True


@dataclass
class RunRecord:
    """A persisted run for the dashboard — survives process restarts (unlike the in-memory
    ledger). Written by the server handler; read by the dashboard."""

    run_id: str
    agent: str
    status: RunStatus = "running"
    parent_run: str | None = None
    halt_reason: str | None = None
    detector: str | None = None
    cost_micros: int = 0
    steps: int = 0
    started_at: float = 0.0
    ended_at: float | None = None
    task: str | None = None

    @property
    def problematic(self) -> bool:
        return self.status in ("halted", "throttled", "error")
