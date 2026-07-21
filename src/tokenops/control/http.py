"""TokenOps HTTP wiring for A2A apps (run registration + governance errors).

A2A stays protocol-only (`create_a2a_app`); entry agents mount registration and
wrap handlers here so Halt/Throttled map to HTTP responses.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Mapping

import httpx
from chronicle.session import reset_session
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from tokenops.control.core import Halt
from tokenops.control.engine import Throttled
from tokenops.control.models import RunAlreadyRegisteredError, RunRegistration, parse_governance_mode
from tokenops.control.store import Store, new_id

Handler = Callable[[dict[str, Any], Mapping[str, str]], Awaitable[dict[str, Any] | Response]]


def _coerce_user_dims(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items()}


def mount_run_registration(app: FastAPI, store: Store) -> None:
    """Mount ``POST /v1/runs`` and begin a Chronicle trace for the registered run."""

    @app.post("/v1/runs")
    async def register_run(request: Request) -> JSONResponse:
        """Entry registration — required before ``POST /v1/tasks`` (#2 split endpoint)."""
        payload = await request.json()
        run_id = str(payload.get("run_id") or "").strip() or new_id("run")
        intent = str(payload.get("intent", ""))
        user_dims = _coerce_user_dims(payload.get("user_dims"))
        try:
            mode = parse_governance_mode(payload.get("mode") or payload.get("governance_mode"))
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        try:
            reg = store.register_run(
                RunRegistration(
                    run_id=run_id, intent=intent, user_dims=user_dims, mode=mode,
                )
            )
        except RunAlreadyRegisteredError as exc:
            return JSONResponse({"error": str(exc)}, status_code=409)
        reset_session().begin_trace(reg.run_id)
        return JSONResponse(
            {"run_id": reg.run_id, "status": "registered", "mode": reg.mode.value},
            status_code=201,
        )


def with_governance_errors(handler: Handler) -> Handler:
    """Wrap a task handler so Halt → 200 halted and Throttled → 429."""

    async def wrapped(
        payload: dict[str, Any], headers: Mapping[str, str],
    ) -> dict[str, Any] | Response:
        try:
            return await handler(payload, headers)
        except Halt as halt:
            return JSONResponse(
                {"status": "halted", "reason": halt.action.reason},
                status_code=200,
            )
        except Throttled as thr:
            retry_after = str(int(thr.action.retry_after_s or 1))
            return JSONResponse(
                {"status": "throttled", "reason": thr.action.reason},
                status_code=429,
                headers={"Retry-After": retry_after},
            )

    return wrapped


def _raise_for_response(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = ""
        try:
            body = response.json()
            if isinstance(body, dict) and body.get("error"):
                detail = f": {body['error']}"
        except Exception:
            pass
        raise httpx.HTTPStatusError(
            f"{exc}{detail}",
            request=exc.request,
            response=exc.response,
        ) from exc


async def post_run(
    url: str,
    payload: dict[str, Any],
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """POST ``/v1/runs`` at *url*. Prefer :class:`~tokenops.control.client.ControlPlaneClient`."""
    base = url.rstrip("/")
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(f"{base}/v1/runs", json=payload)
        _raise_for_response(response)
        return response.json()


def post_run_sync(
    url: str,
    payload: dict[str, Any],
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Sync POST ``/v1/runs`` at *url*. Prefer :class:`~tokenops.control.client.ControlPlaneClient`."""
    base = url.rstrip("/")
    with httpx.Client(timeout=timeout) as client:
        response = client.post(f"{base}/v1/runs", json=payload)
        _raise_for_response(response)
        return response.json()
