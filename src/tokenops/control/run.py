"""Unified trace + governance scope for one hop.

Prefer :func:`tokenops_run` (alias :func:`agentplane_run_scope`) for every hop. A run is a
Chronicle trace: the hop joins the trace of the active (or inbound ``traceparent``) Chronicle
span, attribution is built in memory from the call's own ``intent`` / ``user_dims`` / ``mode``,
and nothing is registered with the control plane.

Governance configuration comes from the control plane (``ControlPlaneClient.governance``,
``ETag`` cached) or from an explicit ``config=``. A fresh Governor is built for each hop.

Failure behaviour (explicit):

- No control plane configured and no ``config=``: raises :class:`RuntimeError`.
- Plane unreachable with a configuration already fetched: the last known configuration is used
  (logged at WARNING). Unreachable with none: :class:`ControlPlaneUnavailable` is raised, so the
  hop does not run ungoverned.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from tokenops.control.attribution import _build_attribution, merge_hop_dims
from tokenops.control.chronicle_trace_utils import chronicle_span
from tokenops.control.config import build_governance_stack, build_governor
from tokenops.control.context import (
    SpanContext,
    _governance_scope,
    bind_hop,
    bind_span,
    run_scope,
)
from tokenops.control.context import (
    clear as clear_run_context,
)
from tokenops.control.core import Attribution
from tokenops.control.crossing import install_crossing_hook
from tokenops.control.engine import ApplyControls, Governor, PreviewControls
from tokenops.control.ledger import PriceFn
from tokenops.control.ledger_writers import writer_for
from tokenops.control.models import GovernanceMode, HopAttribution, parse_governance_mode
from tokenops.control.pricing import build_price_book
from tokenops.control.request_context import current_request_context
from tokenops.repositories import ControlPlaneClient

logger = logging.getLogger("tokenops.run")


@dataclass(frozen=True, kw_only=True)
class TokenOpsBound:
    """Objects bound for one hop under :func:`tokenops_run`."""

    hop: HopAttribution
    span: SpanContext
    attr: Attribution
    governor: Governor
    controls: ApplyControls | PreviewControls
    client: ControlPlaneClient | None

    @property
    def registration(self) -> HopAttribution:
        """Deprecated alias of ``hop``."""
        return self.hop


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

    # Agent kwargs / instrument defaults beat payload for intent & mode.
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
    resolved_dims = merge_hop_dims(agent_dims, body)

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
    config: Mapping[str, Any] | None = None,
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
    async_writes: bool = True,
) -> Iterator[TokenOpsBound]:
    """One hop under a governed trace: join the trace, bind span + governance.

    Happy path (with :func:`~tokenops.control.instrument.instrument_app`)::

        with tokenops_run():
            ...

    ``client`` is the control plane (default: built from ``CONTROL_PLANE_URL``). Pass
    ``config=`` (a governance dict) to run in process with no control plane: spend, in-flight
    and halt are then kept in this process only.

    With a plane, spend and completion writes are queued and sent in the background
    (``async_writes``, ADR 0003); ``admit`` and halt writes stay synchronous. Pass
    ``async_writes=False`` for a synchronous write per crossing.
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
    if governor is None and client is None and config is None:
        client_obj: ControlPlaneClient | None = ControlPlaneClient.from_env()
    else:
        client_obj = client

    with chronicle_span(hdrs, service=svc) as trace:
        reg = HopAttribution(
            trace_id=trace.trace_id,
            intent=resolved_intent,
            user_dims=dict(resolved_dims),
            mode=(
                parse_governance_mode(resolved_mode)
                if resolved_mode not in (None, "")
                else GovernanceMode.ENFORCE
            ),
        )
        span = SpanContext(span_id=trace.span_id, service=svc, parent_span_id=trace.parent_id)
        attr = _build_attribution(reg, service=svc)

        if governor is None:
            price_fn = price if price is not None else build_price_book()
            gov_config = _governance_config(client_obj, config, svc)
            enforce = reg.mode is not GovernanceMode.PREVIEW
            writer = writer_for(client_obj) if client_obj is not None and async_writes else None
            if controls is not None:
                gov = build_governor(
                    gov_config,
                    price_fn,
                    controls,
                    backend=client_obj,
                    writer=writer,
                    enforce=enforce,
                )
                ctrl: ApplyControls | PreviewControls = controls
            else:
                gov, ctrl = build_governance_stack(
                    gov_config, price_fn, backend=client_obj, writer=writer, mode=reg.mode
                )
        else:
            gov = governor
            ctrl = controls if controls is not None else gov.controls  # type: ignore[assignment]

        if open_ledger_run:
            gov.ledger.open_run(reg.trace_id)

        bind_hop(reg)
        bind_span(span)
        try:
            with run_scope(reg, span):
                with _governance_scope(gov, attr, provider=prov or "", model=mdl or ""):
                    yield TokenOpsBound(
                        hop=reg,
                        span=span,
                        attr=attr,
                        governor=gov,
                        controls=ctrl,
                        client=client_obj,
                    )
        finally:
            clear_run_context()
            if open_ledger_run:
                # Drop this process's LocalRunState so a long-lived / shared-governor process
                # does not leak per-trace window state.
                gov.ledger.close_run(reg.trace_id)


def _governance_config(
    client: ControlPlaneClient | None, config: Mapping[str, Any] | None, agent: str
) -> Mapping[str, Any]:
    if config is not None:
        return config
    if client is None:
        raise RuntimeError("no governance config: pass config= or point at a control plane")
    result = client.governance(agent)
    if result.stale:
        logger.warning(
            "tokenops.governance_stale agent=%s: control plane unreachable, using the last "
            "known configuration",
            agent,
        )
    return result.config


# Preferred alternate name from design notes §5.
agentplane_run_scope = tokenops_run
