"""Run registration and attribution builders (internal).

Integrators use :func:`~tokenops.control.run.tokenops_run` —
not these helpers directly. Boundaries call :func:`require_registration`.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Mapping

from tokenops.control.context import (
    BoundRun,
    SpanContext,
    bind_registration,
    bind_span,
    current_registration,
    header_parent_span_id,
    header_run_id,
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


def begin_entry_task_run(
    store: Store,
    *,
    headers: Mapping[str, str],
    payload: Mapping[str, object] | None,
    service: str,
    intent: str | None = None,
    user_dims: Mapping[str, str] | None = None,
    mode: GovernanceMode | str | None = None,
    client: ControlPlaneClient | None = None,
    scrape_payload_dims: bool = True,
) -> BoundRun:
    """Entry agent: reuse inbound ``run_id`` or register a new run via the control plane.

    UI / clients call the entry agent's ``POST /v1/tasks`` without registering first.
    The entry agent opens the run (``ControlPlaneClient.register_run`` → plane
    ``POST /v1/runs`` or embedded Store), then binds context for this task.

    When ``intent`` / ``mode`` / ``user_dims`` are provided (agent definition), they
    win over payload scraping (§1). Set ``scrape_payload_dims=False`` to never take
    intent/mode from the body (``tokenops_run`` path); allow-listed ``user_id`` may
    still merge from payload via :func:`merge_registration_dims`.
    """
    from tokenops.control.client import ControlPlaneClient
    from tokenops.control.context import RUN_ID_HEADER

    rid = header_run_id(headers)
    if rid:
        return begin_downstream_run(store, headers=headers, service=service)

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
        intent=resolved_intent, user_dims=resolved_dims, mode=resolved_mode,
    )
    merged = {str(k): str(v) for k, v in headers.items()}
    merged[RUN_ID_HEADER] = str(registered["run_id"])
    logger.info(
        "tokenops.entry_registered service=%s run_id=%s intent=%s",
        service,
        registered["run_id"],
        resolved_intent,
    )
    return begin_downstream_run(store, headers=merged, service=service)


def require_registration() -> RunRegistration:
    """Fail closed when boundaries run outside a bound request context."""
    reg = current_registration()
    if reg is None:
        raise RunNotRegisteredError("no run registration in request context")
    return reg
