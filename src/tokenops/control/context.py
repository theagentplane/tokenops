"""Request-scoped run context — stack-agnostic via contextvars.

Boundaries and ingest read registration + span from ambient context instead of
threading dims through every handler signature.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from tokenops.control.core import Attribution
from tokenops.control.models import RunRegistration

# HTTP headers for cross-service propagation (see docs/run-attribution.md).
RUN_ID_HEADER = "X-TokenOps-Run-Id"
PARENT_SPAN_ID_HEADER = "X-TokenOps-Parent-Span-Id"


@dataclass(frozen=True, kw_only=True)
class SpanContext:
    span_id: str
    service: str
    parent_span_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class BoundRun:
    registration: RunRegistration
    span: SpanContext


_registration: ContextVar[RunRegistration | None] = ContextVar("run_registration", default=None)
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


def bind_governance(governance: GovernanceContext) -> None:
    _governance.set(governance)


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


def current_registration() -> RunRegistration | None:
    return _registration.get()


def current_span() -> SpanContext | None:
    return _span.get()


def current_bound_run() -> BoundRun | None:
    reg = _registration.get()
    if reg is None:
        return None
    span = _span.get()
    if span is None:
        return None
    return BoundRun(registration=reg, span=span)


def bind_registration(registration: RunRegistration) -> None:
    _registration.set(registration)


def bind_span(span: SpanContext) -> None:
    _span.set(span)


def clear() -> None:
    _registration.set(None)
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
def run_scope(registration: RunRegistration, span: SpanContext) -> Iterator[BoundRun]:
    """Install registration + span for one request; restored on exit."""
    tok_reg = _registration.set(registration)
    tok_span = _span.set(span)
    try:
        yield BoundRun(registration=registration, span=span)
    finally:
        _registration.reset(tok_reg)
        _span.reset(tok_span)


def header_run_id(headers: Mapping[str, str]) -> str | None:
    for key, value in headers.items():
        if key.lower() == RUN_ID_HEADER.lower():
            v = (value or "").strip()
            return v or None
    return None


def header_parent_span_id(headers: Mapping[str, str]) -> str | None:
    for key, value in headers.items():
        if key.lower() == PARENT_SPAN_ID_HEADER.lower():
            v = (value or "").strip()
            return v or None
    return None
