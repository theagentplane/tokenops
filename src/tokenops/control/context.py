"""Request-scoped run context — stack-agnostic via contextvars.

Boundaries and ingest read the hop attribution + span from ambient context instead of
threading dims through every handler signature.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from tokenops.control.core import Attribution
from tokenops.control.models import HopAttribution

# HTTP headers for cross-service propagation (see docs/run-attribution.md).


@dataclass(frozen=True, kw_only=True)
class SpanContext:
    span_id: str
    service: str
    parent_span_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class BoundRun:
    hop: HopAttribution
    span: SpanContext

    @property
    def registration(self) -> HopAttribution:
        """Deprecated alias of ``hop``."""
        return self.hop


_hop: ContextVar[HopAttribution | None] = ContextVar("tokenops_hop", default=None)
_span: ContextVar[SpanContext | None] = ContextVar("run_span", default=None)
_governance: ContextVar[GovernanceContext | None] = ContextVar("governance", default=None)
_current_controls: ContextVar[Any | None] = ContextVar("current_controls", default=None)


@dataclass(frozen=True, kw_only=True)
class GovernanceContext:
    """Bound governor + attribution for ``@boundary`` ingest within a request."""

    governor: Any
    attr: Attribution
    provider: str = ""
    model: str = ""


def current_governance() -> GovernanceContext | None:
    return _governance.get()


def clear_governance() -> None:
    _governance.set(None)


def current_controls() -> Any:
    """Return the active ``AgentControls`` for the current governed call, or ``None``."""
    return _current_controls.get()


def set_current_controls(controls: Any) -> Any:
    """Set the active controls context; returns a token for ``reset_current_controls``."""
    return _current_controls.set(controls)


def reset_current_controls(token: Any) -> None:
    """Reset the controls context to its previous value."""
    _current_controls.reset(token)


def current_hop() -> HopAttribution | None:
    return _hop.get()


def current_span() -> SpanContext | None:
    return _span.get()


def bind_hop(hop: HopAttribution) -> None:
    _hop.set(hop)


def bind_span(span: SpanContext) -> None:
    _span.set(span)


def clear() -> None:
    _hop.set(None)
    _span.set(None)
    _governance.set(None)
    _current_controls.set(None)


@contextmanager
def _governance_scope(
    governor: object,
    attr: Attribution,
    *,
    provider: str = "",
    model: str = "",
) -> Iterator[GovernanceContext]:
    """Install governor context for ``@boundary`` (used by :func:`~tokenops.control.run.tokenops_run`)."""
    ctx = GovernanceContext(governor=governor, attr=attr, provider=provider, model=model)
    tok = _governance.set(ctx)
    try:
        yield ctx
    finally:
        _governance.reset(tok)


@contextmanager
def run_scope(hop: HopAttribution, span: SpanContext) -> Iterator[BoundRun]:
    """Install the hop attribution + span for one request; restored on exit."""
    tok_reg = _hop.set(hop)
    tok_span = _span.set(span)
    try:
        yield BoundRun(hop=hop, span=span)
    finally:
        _hop.reset(tok_reg)
        _span.reset(tok_span)


# Deprecated names kept for 1.x.
current_registration = current_hop
bind_registration = bind_hop
