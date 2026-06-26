from __future__ import annotations

from typing import Any, Awaitable, Callable

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import uvicorn

from tokenops.a2a.cards import agent_card
from tokenops.control import Halt
from tokenops.control.engine import Throttled

Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


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
    async def run_task(payload: dict[str, Any]) -> JSONResponse:
        # Handlers normally catch Halt/Throttled themselves (to write a RunRecord + return a
        # partial). These are safety nets: Halt is a BaseException and would otherwise escape
        # the broad `except Exception` and crash the worker.
        try:
            result = await handler(payload)
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


async def post_task(url: str, payload: dict[str, Any], timeout: float = 300.0) -> dict[str, Any]:
    base = url.rstrip("/")
    async with httpx.AsyncClient(timeout=timeout) as client:
        health = await client.get(f"{base}/health")
        health.raise_for_status()
        response = await client.post(f"{base}/v1/tasks", json=payload)
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


def post_task_sync(url: str, payload: dict[str, Any], timeout: float = 300.0) -> dict[str, Any]:
    base = url.rstrip("/")
    with httpx.Client(timeout=timeout) as client:
        health = client.get(f"{base}/health")
        health.raise_for_status()
        response = client.post(f"{base}/v1/tasks", json=payload)
        _raise_for_response(response)
        return response.json()


def fetch_agent_card_sync(url: str) -> dict[str, Any]:
    base = url.rstrip("/")
    with httpx.Client(timeout=10.0) as client:
        response = client.get(f"{base}/.well-known/agent-card.json")
        response.raise_for_status()
        return response.json()
