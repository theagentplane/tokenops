"""Run registration and attribution builders.

Entry services call :func:`begin_entry_run`; downstream services call
:func:`begin_downstream_run`. Boundaries call :func:`require_registration`.
"""

from __future__ import annotations

import logging
from typing import Mapping

from tokenops.control.context import (
    BoundRun,
    SpanContext,
    bind_registration,
    bind_span,
    current_registration,
    header_parent_span_id,
    header_run_id,
    run_scope,
)
from tokenops.control.core import Attribution
from tokenops.control.models import RunNotRegisteredError, RunRegistration
from tokenops.control.store import Store, new_id

logger = logging.getLogger("tokenops.attribution")


def _coerce_user_dims(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items()}


def build_attribution(reg: RunRegistration, *, service: str) -> Attribution:
    """Map registration + boundary ``service`` to the legacy ``Attribution`` ledger/policies use."""
    tags = dict(reg.user_dims)
    if reg.intent:
        tags.setdefault("intent", reg.intent)
    user = reg.user_dims.get("user_id", reg.user_dims.get("user", "unknown"))
    return Attribution(user=user, agent=service, run_id=reg.run_id, tags=tags)


def begin_entry_run(
    store: Store,
    *,
    headers: Mapping[str, str],
    payload: dict,
    service: str,
    run_id: str | None = None,
) -> BoundRun:
    """Register a new run and bind request context. Entry boundary only."""
    rid = run_id or header_run_id(headers) or str(payload.get("run_id") or "").strip() or new_id("run")
    intent = str(payload.get("intent", ""))
    user_dims = _coerce_user_dims(payload.get("user_dims"))
    reg = store.register_run(RunRegistration(run_id=rid, intent=intent, user_dims=user_dims))
    span = SpanContext(span_id=new_id("span"), service=service, parent_span_id=header_parent_span_id(headers))
    bind_registration(reg)
    bind_span(span)
    return BoundRun(registration=reg, span=span)


def begin_downstream_run(
    store: Store,
    *,
    headers: Mapping[str, str],
    service: str,
) -> BoundRun:
    """Resolve registration and bind a *new* span for this agent hop.

    Missing ``X-TokenOps-Run-Id`` no longer refuses work: we auto-register an
    unattributed run and log so cross-agent stitching is visibly broken.
    Each call still opens a fresh span (parent from the inbound header when set).
    """
    rid = header_run_id(headers)
    if not rid:
        rid = new_id("run")
        logger.warning(
            "tokenops.missing_run_id service=%s auto_run_id=%s "
            "cross_agent_attribution_broken=1 — governing locally; "
            "propagate X-TokenOps-Run-Id for shared-run budgets",
            service,
            rid,
        )
        reg = store.register_run(
            RunRegistration(
                run_id=rid,
                intent="unattributed",
                user_dims={"tokenops_soft_run": "1", "service": service},
            )
        )
    else:
        reg = store.resolve_run(rid)
    span = SpanContext(
        span_id=new_id("span"),
        service=service,
        parent_span_id=header_parent_span_id(headers),
    )
    bind_registration(reg)
    bind_span(span)
    return BoundRun(registration=reg, span=span)


def require_registration() -> RunRegistration:
    """Fail closed when boundaries run outside a bound request context."""
    reg = current_registration()
    if reg is None:
        raise RunNotRegisteredError("no run registration in request context")
    return reg


def entry_run_scope(
    store: Store,
    *,
    headers: Mapping[str, str],
    payload: dict,
    service: str,
    run_id: str | None = None,
):
    """Context manager: register, bind span, clear on exit."""
    bound = begin_entry_run(store, headers=headers, payload=payload, service=service, run_id=run_id)
    return run_scope(bound.registration, bound.span)


def downstream_run_scope(
    store: Store,
    *,
    headers: Mapping[str, str],
    service: str,
):
    """Context manager: resolve, bind span, clear on exit."""
    bound = begin_downstream_run(store, headers=headers, service=service)
    return run_scope(bound.registration, bound.span)
