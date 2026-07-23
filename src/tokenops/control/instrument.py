"""FastAPI instrumentation — bind RequestContext + install crossing hook (§7, §17)."""

from __future__ import annotations

import json
import logging
from typing import Any, Mapping

from fastapi import FastAPI, Request

from tokenops.control.crossing import install_crossing_hook
from tokenops.control.models import GovernanceMode
from tokenops.control.request_context import RequestContext, reset_request_context, set_request_context

logger = logging.getLogger("tokenops.instrument")


def instrument_app(
    app: FastAPI,
    *,
    service: str,
    intent: str | None = None,
    user_dims: Mapping[str, str] | None = None,
    mode: GovernanceMode | str | None = None,
    provider: str = "",
    model: str = "",
) -> FastAPI:
    """Install TokenOps middleware on a FastAPI app.

    * Calls :func:`~tokenops.control.crossing.install_crossing_hook` (idempotent).
    * On each request: reads headers + JSON body into :class:`RequestContext`
      (with agent defaults), so handlers can use ``with tokenops_run():``.

    Returns ``app`` for chaining.
    """
    install_crossing_hook()

    agent_dims = dict(user_dims) if user_dims else None

    @app.middleware("http")
    async def tokenops_request_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        headers = {str(k): str(v) for k, v in request.headers.items()}
        payload: dict[str, Any] | None = None
        body = await request.body()
        if body:
            try:
                loaded = json.loads(body)
                if isinstance(loaded, dict):
                    payload = loaded
            except (json.JSONDecodeError, UnicodeDecodeError):
                payload = None

        # Re-inject body so downstream FastAPI handlers can still read it.
        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "body": body, "more_body": False}

        request = Request(request.scope, receive)
        ctx = RequestContext(
            headers=headers,
            payload=payload,
            service=service,
            intent=intent,
            user_dims=agent_dims,
            mode=mode,
            provider=provider,
            model=model,
        )
        token = set_request_context(ctx)
        try:
            return await call_next(request)
        finally:
            reset_request_context(token)

    logger.debug("tokenops.instrument_app service=%s", service)
    return app
