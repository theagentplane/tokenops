"""Ambient HTTP request context for TokenOps scopes (design notes §7).

Middleware / tests bind headers, payload, and agent defaults so
:func:`~tokenops.control.run.tokenops_run` can omit those arguments.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Mapping

from tokenops.control.models import GovernanceMode


@dataclass(frozen=True, kw_only=True)
class RequestContext:
    """Per-request ambient inputs for the happy-path ``tokenops_run()``."""

    headers: Mapping[str, str] = field(default_factory=dict)
    payload: Mapping[str, Any] | None = None
    service: str = ""
    # Agent-definition defaults (design notes §1) — not scraped from UI payload.
    intent: str | None = None
    user_dims: Mapping[str, str] | None = None
    mode: GovernanceMode | str | None = None
    provider: str = ""
    model: str = ""


_request: ContextVar[RequestContext | None] = ContextVar("tokenops_request", default=None)


def current_request_context() -> RequestContext | None:
    return _request.get()


def bind_request_context(ctx: RequestContext) -> None:
    """Install ambient request context (tests / non-middleware callers)."""
    _request.set(ctx)


def clear_request_context() -> None:
    _request.set(None)


def reset_request_context(token: Any) -> None:
    """Restore a previous ContextVar token from middleware."""
    _request.reset(token)


def set_request_context(ctx: RequestContext) -> Any:
    """Set context and return a reset token (for middleware finally blocks)."""
    return _request.set(ctx)
