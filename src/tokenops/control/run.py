"""Unified run + governance scope (design notes §5, §8, §9, §1, §7, §6).

Prefer :func:`tokenops_run` (alias :func:`agentplane_run_scope`) for every hop.
Happy path uses :class:`~tokenops.control.client.ControlPlaneClient` only —
callers need not pass ``store=`` (§6). Governance config is read via the client
(process-cached; §10); a fresh Governor is built each run from that config.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass

from tokenops.control.attribution import (
    _build_attribution,
    begin_downstream_run,
    begin_entry_task_run,
    merge_registration_dims,
)
from tokenops.control.client import ControlPlaneClient
from tokenops.control.config import build_governance_stack, build_governor
from tokenops.control.context import (
    BoundRun,
    SpanContext,
    _governance_scope,
    run_scope,
)
from tokenops.control.context import (
    clear as clear_run_context,
)
from tokenops.control.core import Attribution
from tokenops.control.crossing import install_crossing_hook
from tokenops.control.engine import ApplyControls, Governor, PreviewControls
from tokenops.control.ledger import PriceFn
from tokenops.control.models import GovernanceMode, RunRegistration, parse_governance_mode
from tokenops.control.pricing import build_price_book
from tokenops.control.request_context import current_request_context
from tokenops.control.store import Store

logger = logging.getLogger("tokenops.run")


@dataclass(frozen=True, kw_only=True)
class TokenOpsBound:
    """Objects bound for one hop under :func:`tokenops_run`."""

    registration: RunRegistration
    span: SpanContext
    attr: Attribution
    governor: Governor
    controls: ApplyControls | PreviewControls
    client: ControlPlaneClient
    store: Store  # escape hatch — prefer client APIs (§6)


def _obtain_client(
    *,
    store: Store | None,
    client: ControlPlaneClient | None,
) -> ControlPlaneClient:
    if client is not None:
        if store is not None and client.embedded and client.store is not store:
            # Tests often pass an explicit Store; prefer it for registration visibility.
            return ControlPlaneClient(store=store)
        return client
    if store is not None:
        return ControlPlaneClient(store=store)
    return ControlPlaneClient.from_env()


def _resolve_ambient(
    *,
    headers: Mapping[str, str] | None,
    payload: Mapping[str, object] | None,
    service: str | None,
    intent: str | None,
    user_dims: Mapping[str, str] | None,
    mode: GovernanceMode | str | None,
    provider: str | None,
    model: str | None,
) -> tuple[
    Mapping[str, str],
    Mapping[str, object] | None,
    str,
    str,
    dict[str, str],
    GovernanceMode | str | None,
    str,
    str,
]:
    rc = current_request_context()

    hdrs: Mapping[str, str]
    if headers is not None:
        hdrs = headers
    elif rc is not None:
        hdrs = rc.headers
    else:
        hdrs = {}

    body: Mapping[str, object] | None
    if payload is not None:
        body = payload
    elif rc is not None:
        body = rc.payload
    else:
        body = None

    svc = service if service is not None else (rc.service if rc else "")
    if not svc:
        raise ValueError(
            "tokenops_run requires service=... or ambient RequestContext.service "
            "(via instrument_app / bind_request_context)"
        )

    # §1: agent kwargs / instrument defaults beat payload for intent & mode.
    if intent is not None:
        resolved_intent = intent
    elif rc is not None and rc.intent is not None:
        resolved_intent = rc.intent
    else:
        resolved_intent = ""

    agent_dims: Mapping[str, str] | None
    if user_dims is not None:
        agent_dims = user_dims
    elif rc is not None and rc.user_dims is not None:
        agent_dims = rc.user_dims
    else:
        agent_dims = None
    resolved_dims = merge_registration_dims(agent_dims, body)

    if mode is not None:
        resolved_mode: GovernanceMode | str | None = mode
    elif rc is not None and rc.mode is not None:
        resolved_mode = rc.mode
    else:
        resolved_mode = None

    prov = provider if provider is not None else (rc.provider if rc else "")
    mdl = model if model is not None else (rc.model if rc else "")
    return hdrs, body, svc, resolved_intent, resolved_dims, resolved_mode, prov, mdl


@contextmanager
def tokenops_run(
    *,
    client: ControlPlaneClient | None = None,
    store: Store | None = None,
    headers: Mapping[str, str] | None = None,
    payload: Mapping[str, object] | None = None,
    service: str | None = None,
    intent: str | None = None,
    user_dims: Mapping[str, str] | None = None,
    mode: GovernanceMode | str | None = None,
    provider: str | None = None,
    model: str | None = None,
    price: PriceFn | None = None,
    governor: Governor | None = None,
    controls: ApplyControls | PreviewControls | None = None,
    open_ledger_run: bool = True,
) -> Iterator[TokenOpsBound]:
    """One hop under a governed run: register-or-join, bind span + governance.

    Happy path (with :func:`~tokenops.control.instrument.instrument_app`)::

        with tokenops_run():
            ...

    Does not require the caller to pass ``store=`` or build ``Attribution``.
    Optional ``store=`` remains for tests; prefer ``client=`` / ``from_env``.
    """
    install_crossing_hook()

    hdrs, body, svc, resolved_intent, resolved_dims, resolved_mode, prov, mdl = _resolve_ambient(
        headers=headers,
        payload=payload,
        service=service,
        intent=intent,
        user_dims=user_dims,
        mode=mode,
        provider=provider,
        model=model,
    )
    client_obj = _obtain_client(store=store, client=client)
    store_obj = store if store is not None else client_obj.require_store()

    from tokenops.control.context import header_run_id

    if header_run_id(hdrs):
        bound: BoundRun = begin_downstream_run(store_obj, headers=hdrs, service=svc)
    else:
        bound = begin_entry_task_run(
            store_obj,
            headers=hdrs,
            payload=body,
            service=svc,
            intent=resolved_intent,
            user_dims=resolved_dims,
            mode=resolved_mode,
            client=client_obj,
            scrape_payload_dims=False,
        )

    reg = bound.registration
    attr = _build_attribution(reg, service=svc)

    # Mode: explicit override → registration → enforce.
    if resolved_mode is not None and resolved_mode != "":
        gov_mode = (
            resolved_mode
            if isinstance(resolved_mode, GovernanceMode)
            else parse_governance_mode(resolved_mode)
        )
    else:
        gov_mode = reg.mode

    if governor is None:
        price_fn = price if price is not None else build_price_book()
        # §10: cached config (via Store / client); fresh Governor each run — no clone.
        if store is not None:
            config = store_obj.governance_config_for(svc)
        else:
            config = client_obj.governance_config_for(svc)
        if controls is not None:
            enforce = gov_mode is not GovernanceMode.PREVIEW
            gov = build_governor(
                config,
                price_fn,
                controls,
                store=store_obj,
                enforce=enforce,
            )
            ctrl = controls
        else:
            gov, ctrl = build_governance_stack(
                config,
                price_fn,
                store=store_obj,
                mode=gov_mode,
            )
    else:
        gov = governor
        ctrl = controls if controls is not None else gov.controls  # type: ignore[assignment]

    if open_ledger_run:
        gov.ledger.open_run(reg.run_id)

    # begin_* binds registration before run_scope; run_scope.reset restores that
    # bind on exit — clear hop leftovers so ambient context does not leak.
    try:
        with run_scope(reg, bound.span):
            with _governance_scope(gov, attr, provider=prov or "", model=mdl or ""):
                yield TokenOpsBound(
                    registration=reg,
                    span=bound.span,
                    attr=attr,
                    governor=gov,
                    controls=ctrl,
                    client=client_obj,
                    store=store_obj,
                )
    finally:
        clear_run_context()


# Preferred alternate name from design notes §5.
agentplane_run_scope = tokenops_run
