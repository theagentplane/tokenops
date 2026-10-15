"""Run registration and attribution builders (internal).

Integrators use :func:`~tokenops.control.run.tokenops_run` —
not these helpers directly. Boundaries call :func:`require_registration`.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING

from tokenops.control.context import (
    BoundRun,
    SpanContext,
    bind_registration,
    bind_span,
    current_registration,
)
from tokenops.control.core import Attribution
from tokenops.control.models import (
    GovernanceMode,
    RunNotRegisteredError,
    RunRegistration,
)
from tokenops.control.store import Store, new_id

if TYPE_CHECKING:
    from tokenops.control.client import ControlPlaneClient

logger = logging.getLogger("tokenops.attribution")

# Payload keys allowed to merge into user_dims when the agent owns intent/mode (§1).
_PAYLOAD_USER_DIM_ALLOWLIST = frozenset({"user_id", "user"})


def _coerce_user_dims(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items()}


def merge_registration_dims(
    agent_dims: Mapping[str, str] | None,
    payload: Mapping[str, object] | None,
) -> dict[str, str]:
    """Agent ``user_dims`` first; allow-listed client keys fill gaps only."""
    dims = {str(k): str(v) for k, v in (agent_dims or {}).items()}
    body = dict(payload or {})
    payload_dims = _coerce_user_dims(body.get("user_dims"))
    for key in _PAYLOAD_USER_DIM_ALLOWLIST:
        if key in dims:
            continue
        if key in payload_dims:
            dims[key] = payload_dims[key]
        elif key in body and body[key] is not None and str(body[key]).strip():
            dims[key] = str(body[key])
    return dims


def _build_attribution(reg: RunRegistration, *, service: str) -> Attribution:
    """Map registration + boundary ``service`` to ledger/policy ``Attribution``."""
    tags = dict(reg.user_dims)
    if reg.intent:
        tags.setdefault("intent", reg.intent)
    user = reg.user_dims.get("user_id", reg.user_dims.get("user", "unknown"))
    return Attribution(user=user, agent=service, trace_id=reg.trace_id, tags=tags)


def begin_entry_run(
    store: Store,
    *,
    payload: dict,
    service: str,
    trace_id: str | None = None,
    parent_span_id: str | None = None,
    span_id: str | None = None,
) -> BoundRun:
    """Register a new run and bind request context. Entry boundary only."""
    rid = trace_id or str(payload.get("trace_id") or "").strip() or new_id("run")
    intent = str(payload.get("intent", ""))
    user_dims = _coerce_user_dims(payload.get("user_dims"))
    reg = store.register_run(RunRegistration(trace_id=rid, intent=intent, user_dims=user_dims))
    span = SpanContext(
        span_id=span_id or new_id("span"), service=service, parent_span_id=parent_span_id
    )
    bind_registration(reg)
    bind_span(span)
    return BoundRun(registration=reg, span=span)


def begin_downstream_run(
    store: Store,
    *,
    trace_id: str | None,
    service: str,
    parent_span_id: str | None = None,
    span_id: str | None = None,
) -> BoundRun:
    """Resolve registration and bind a *new* span for this agent hop.

    The run is the Chronicle trace. Without a ``trace_id`` we auto-register an
    unattributed run and log so cross-agent stitching is visibly broken.
    Each call still opens a fresh span (parent from the inbound trace context when set).
    """
    rid = trace_id
    if not rid:
        rid = new_id("run")
        logger.warning(
            "tokenops.missing_trace_id service=%s auto_trace_id=%s "
            "cross_agent_attribution_broken=1 — governing locally; "
            "propagate the W3C traceparent for shared-run budgets",
            service,
            rid,
        )
        reg = store.register_run(
            RunRegistration(
                trace_id=rid,
                intent="unattributed",
                user_dims={"tokenops_soft_run": "1", "service": service},
            )
        )
    else:
        reg = store.resolve_run(rid)
    span = SpanContext(
        span_id=span_id or new_id("span"),
        service=service,
        parent_span_id=parent_span_id,
    )
    bind_registration(reg)
    bind_span(span)
    return BoundRun(registration=reg, span=span)


def begin_entry_task_run(
    store: Store,
    *,
    trace_id: str | None,
    payload: Mapping[str, object] | None,
    service: str,
    parent_span_id: str | None = None,
    span_id: str | None = None,
    intent: str | None = None,
    user_dims: Mapping[str, str] | None = None,
    mode: GovernanceMode | str | None = None,
    client: ControlPlaneClient | None = None,
    scrape_payload_dims: bool = True,
) -> BoundRun:
    """Join the run for ``trace_id`` if it is registered, else register it.

    The run is the Chronicle trace: a downstream hop arrives with the caller's trace id (from
    ``traceparent``) and joins; the entry hop sees an unregistered trace and registers it.

    UI / clients call the entry agent's ``POST /v1/tasks`` without registering first.
    The entry agent opens the run (``ControlPlaneClient.register_run`` → plane
    ``POST /v1/runs`` or embedded Store), then binds context for this task.

    When ``intent`` / ``mode`` / ``user_dims`` are provided (agent definition), they
    win over payload scraping (§1). Set ``scrape_payload_dims=False`` to never take
    intent/mode from the body (``tokenops_run`` path); allow-listed ``user_id`` may
    still merge from payload via :func:`merge_registration_dims`.
    """
    from tokenops.control.client import ControlPlaneClient

    if trace_id:
        try:
            store.resolve_run(trace_id)
        except RunNotRegisteredError:
            pass
        else:
            return begin_downstream_run(
                store,
                trace_id=trace_id,
                service=service,
                parent_span_id=parent_span_id,
                span_id=span_id,
            )

    body = dict(payload or {})
    if intent is not None:
        resolved_intent = intent
    elif scrape_payload_dims:
        resolved_intent = str(body.get("intent", "") or "")
    else:
        resolved_intent = ""

    if user_dims is not None:
        # Agent dims + allow-listed payload overrides only.
        resolved_dims = merge_registration_dims(user_dims, body)
    elif scrape_payload_dims:
        resolved_dims = _coerce_user_dims(body.get("user_dims"))
    else:
        resolved_dims = merge_registration_dims(None, body)

    if mode is not None:
        resolved_mode: GovernanceMode | str | None = mode
    elif scrape_payload_dims:
        resolved_mode = body.get("mode") or body.get("governance_mode")  # type: ignore[assignment]
    else:
        resolved_mode = None

    plane = client or ControlPlaneClient.from_env()
    # Prefer the agent Store when embedded so registration is visible immediately.
    if plane.embedded:
        plane = ControlPlaneClient(store=store)
    registered = plane.register_run(
        intent=resolved_intent,
        user_dims=resolved_dims,
        mode=resolved_mode,
        trace_id=trace_id,
    )
    logger.info(
        "tokenops.entry_registered service=%s trace_id=%s intent=%s",
        service,
        registered["trace_id"],
        resolved_intent,
    )
    return begin_downstream_run(
        store,
        trace_id=str(registered["trace_id"]),
        service=service,
        parent_span_id=parent_span_id,
        span_id=span_id,
    )


def require_registration() -> RunRegistration:
    """Fail closed when boundaries run outside a bound request context."""
    reg = current_registration()
    if reg is None:
        raise RunNotRegisteredError("no run registration in request context")
    return reg
