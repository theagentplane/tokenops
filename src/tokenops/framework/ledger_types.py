"""Shapes exchanged with the control plane's governance and ledger routes (1.0).

A run is a Chronicle trace, so everything per run is keyed by ``trace_id``. The control plane
stores no step window and no per-policy statistics (control-plane ADR 0009), and ledger events
carry no idempotency key (ADR 0007): there is no ``step`` kind and no ``deduped`` result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

EventKind = Literal["spent_add", "admit", "complete", "halt_mark", "halt_clear"]


class BudgetTarget(TypedDict):
    """One accumulator a ``spent_add`` is charged to."""

    budget_id: str
    segment_key: str
    period: str


class LedgerEvent(TypedDict, total=False):
    """One ledger mutation, in the control plane's wire shape.

    ``kind`` and ``trace_id`` are required. ``spent_add`` also needs ``delta_micros`` and
    ``targets``; ``admit`` and ``complete`` need ``segment_key``; ``halt_mark`` takes ``reason``.
    """

    kind: EventKind
    trace_id: str
    delta_micros: int
    targets: list[BudgetTarget]
    segment_key: str
    reason: str


@dataclass(frozen=True)
class PrecheckRequest:
    """One read for a pre-call pass."""

    trace_id: str
    segment_keys: list[str] = field(default_factory=list)
    budgets: list[BudgetTarget] = field(default_factory=list)
    want: list[str] = field(default_factory=lambda: ["spent", "inflight", "halt"])


@dataclass(frozen=True)
class PrecheckResult:
    """Halt, spend and in-flight for one trace.

    ``spent`` is keyed ``"<budget_id>|<segment_key>|<period>"``; ``inflight`` by segment key.
    """

    halted: bool = False
    halt_reason: str | None = None
    spent: dict[str, int] = field(default_factory=dict)
    inflight: dict[str, int] = field(default_factory=dict)
    server_ts: float = 0.0


@dataclass(frozen=True)
class ApplyResult:
    """What ``events:batch`` reports for an applied batch."""

    accepted: int = 0
    atomic: bool = True
    totals: dict[str, int] = field(default_factory=dict)
    halted: bool = False


@dataclass(frozen=True)
class HaltStatus:
    """Whether a trace is halted, and why."""

    halted: bool
    reason: str | None = None


@dataclass(frozen=True)
class GovernanceResult:
    """The governance dict for one agent and the ``ETag`` it was served with.

    ``stale`` is true when the control plane could not be reached and the last known
    configuration was returned instead.
    """

    config: dict[str, Any]
    etag: str | None = None
    stale: bool = False
