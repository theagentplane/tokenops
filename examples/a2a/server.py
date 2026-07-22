from __future__ import annotations

from typing import Any, Awaitable, Callable, Mapping

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
import uvicorn

from examples.a2a.cards import agent_card

Handler = Callable[[dict[str, Any], Mapping[str, str]], Awaitable[dict[str, Any] | Response]]


def create_a2a_app(
    name: str,
    description: str,
    base_url: str,
    skills: list[str],
    handler: Handler,
) -> FastAPI:
    app = FastAPI(title=name)
    card = agent_card(name=name, description=description, url=base_url, skills=skills)

    @app.get("/.well-known/agent-card.json")
    async def get_card() -> dict[str, Any]:
        return card

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "agent": name}

    @app.post("/v1/tasks")
    async def run_task(request: Request) -> Response:
        payload = await request.json()
        headers = {k: v for k, v in request.headers.items()}
        try:
            result = await handler(payload, headers)
            if isinstance(result, Response):
                return result
            return JSONResponse(result)
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)

    return app


def run_server(app: FastAPI, port: int) -> None:
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


async def post_task(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 300.0,
) -> dict[str, Any]:
    from tokenops.control.propagate import merge_propagation_headers

    base = url.rstrip("/")
    outbound = merge_propagation_headers(headers)
    async with httpx.AsyncClient(timeout=timeout) as client:
        health = await client.get(f"{base}/health")
        health.raise_for_status()
        response = await client.post(f"{base}/v1/tasks", json=payload, headers=outbound)
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
    from tokenops.control.propagate import merge_propagation_headers

    base = url.rstrip("/")
    outbound = merge_propagation_headers(headers)
    with httpx.Client(timeout=timeout) as client:
        health = client.get(f"{base}/health")
        health.raise_for_status()
        response = client.post(f"{base}/v1/tasks", json=payload, headers=outbound)
        _raise_for_response(response)
        return response.json()


def fetch_agent_card_sync(url: str) -> dict[str, Any]:
    base = url.rstrip("/")
    with httpx.Client(timeout=10.0) as client:
        response = client.get(f"{base}/.well-known/agent-card.json")
        response.raise_for_status()
        return response.json()
