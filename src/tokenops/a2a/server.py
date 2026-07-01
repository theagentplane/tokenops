from __future__ import annotations

from typing import Any, Awaitable, Callable, Mapping

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

from tokenops.a2a.cards import agent_card
from tokenops.chronicle.session import reset_session
from tokenops.control import Halt
from tokenops.control.engine import Throttled
from tokenops.control.models import RunAlreadyRegisteredError, RunRegistration
from tokenops.control.store_factory import control_plane_url, open_store, registration_base_url
from tokenops.control.store import Store, new_id

Handler = Callable[[dict[str, Any], Mapping[str, str]], Awaitable[dict[str, Any]]]


def _coerce_user_dims(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items()}


def create_a2a_app(
    name: str,
    description: str,
    base_url: str,
    skills: list[str],
    handler: Handler,
    *,
    store: Store | None = None,
) -> FastAPI:
    app = FastAPI(title=name)
    card = agent_card(name=name, description=description, url=base_url, skills=skills)

    @app.get("/.well-known/agent-card.json")
    async def get_card() -> dict[str, Any]:
        return card

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "agent": name}

    if store is not None and control_plane_url() is None:

        @app.post("/v1/runs")
        async def register_run(request: Request) -> JSONResponse:
            """Entry registration — required before ``POST /v1/tasks`` (#2 split endpoint)."""
            payload = await request.json()
            run_id = str(payload.get("run_id") or "").strip() or new_id("run")
            intent = str(payload.get("intent", ""))
            user_dims = _coerce_user_dims(payload.get("user_dims"))
            try:
                reg = store.register_run(
                    RunRegistration(run_id=run_id, intent=intent, user_dims=user_dims)
                )
            except RunAlreadyRegisteredError as exc:
                return JSONResponse({"error": str(exc)}, status_code=409)
            reset_session().begin_trace(reg.run_id)
            return JSONResponse({"run_id": reg.run_id, "status": "registered"}, status_code=201)

    @app.post("/v1/tasks")
    async def run_task(request: Request) -> JSONResponse:
        payload = await request.json()
        headers = {k: v for k, v in request.headers.items()}
        try:
            result = await handler(payload, headers)
            return JSONResponse(result)
        except Halt as halt:
            return JSONResponse({"status": "halted", "reason": halt.action.reason}, status_code=200)
        except Throttled as thr:
            retry_after = str(int(thr.action.retry_after_s or 1))
            return JSONResponse({"status": "throttled", "reason": thr.action.reason},
                                status_code=429, headers={"Retry-After": retry_after})
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)

    return app


def run_server(app: FastAPI, port: int) -> None:
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


async def post_run(
    url: str,
    payload: dict[str, Any],
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    base = registration_base_url(url)
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
    base = registration_base_url(url)
    with httpx.Client(timeout=timeout) as client:
        response = client.post(f"{base}/v1/runs", json=payload)
        _raise_for_response(response)
        return response.json()


async def post_task(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 300.0,
) -> dict[str, Any]:
    base = url.rstrip("/")
    async with httpx.AsyncClient(timeout=timeout) as client:
        health = await client.get(f"{base}/health")
        health.raise_for_status()
        response = await client.post(f"{base}/v1/tasks", json=payload, headers=headers or {})
        _raise_for_response(response)
        return response.json()


async def fetch_agent_card(url: str) -> dict[str, Any]:
    base = url.rstrip("/")
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(f"{base}/.well-known/agent-card.json")
        response.raise_for_status()
        return response.json()


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


def post_task_sync(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 300.0,
) -> dict[str, Any]:
    base = url.rstrip("/")
    with httpx.Client(timeout=timeout) as client:
        health = client.get(f"{base}/health")
        health.raise_for_status()
        response = client.post(f"{base}/v1/tasks", json=payload, headers=headers or {})
        _raise_for_response(response)
        return response.json()


def fetch_agent_card_sync(url: str) -> dict[str, Any]:
    base = url.rstrip("/")
    with httpx.Client(timeout=10.0) as client:
        response = client.get(f"{base}/.well-known/agent-card.json")
        response.raise_for_status()
        return response.json()
