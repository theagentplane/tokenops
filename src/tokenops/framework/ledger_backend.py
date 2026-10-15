"""What the ledger needs from a shared store, as protocols.

The framework does no I/O. A :class:`LedgerBackend` is the read and write path to a shared
ledger, and a :class:`LedgerWriter` is an asynchronous sink for spend events; both are
implemented in :mod:`tokenops.repositories` (``ControlPlaneClient``, ``LedgerEventWriter``).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from tokenops.framework.ledger_types import (
    ApplyResult,
    LedgerEvent,
    PrecheckRequest,
    PrecheckResult,
)

__all__ = ["LedgerBackend", "LedgerWriter"]


class LedgerBackend(Protocol):
    """Synchronous access to the shared ledger."""

    def precheck(self, request: PrecheckRequest) -> PrecheckResult:
        """Read halt, spend and in-flight state for one trace."""

    def apply_events(self, events: list[LedgerEvent]) -> ApplyResult:
        """Apply a batch of ledger events in order, once."""


class LedgerWriter(Protocol):
    """Asynchronous delivery of ledger events."""

    def submit(self, events: Sequence[LedgerEvent]) -> int:
        """Queue events; return how many were accepted."""

    def flush(self, timeout: float = 5.0) -> bool:
        """Wait until queued events are sent or dropped (``False`` on timeout)."""
