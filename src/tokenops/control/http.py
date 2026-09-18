"""TokenOps HTTP wiring for A2A apps (run registration + governance errors).

A2A stays protocol-only (`create_a2a_app`); entry agents mount registration and
wrap handlers here so Halt/Throttled map to HTTP responses.
"""

from __future__ import annotations

import csv
import io
import json
import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict
from typing import Any

import httpx
from chronicle.session import reset_session
from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from tokenops.control.core import Halt
from tokenops.control.engine import Throttled
from tokenops.control.models import (
    RunAlreadyRegisteredError,
    RunRegistration,
    parse_governance_mode,
)
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
                    run_id=run_id,
                    intent=intent,
                    user_dims=user_dims,
                    mode=mode,
                )
            )
        except RunAlreadyRegisteredError as exc:
            return JSONResponse({"error": str(exc)}, status_code=409)
        reset_session().begin_trace(reg.run_id)
        return JSONResponse(
            {"run_id": reg.run_id, "status": "registered", "mode": reg.mode.value},
            status_code=201,
        )


_EXPORT_CSV_COLUMNS = [
    "run_id",
    "agent",
    "status",
    "cost_micros",
    "steps",
    "started_at",
    "ended_at",
    "duration_s",
    "dims",
    "halt_reason",
    "detector",
    "governance_events",
]


def _run_to_csv_row(rec):  # type: ignore[no-untyped-def]
    d = asdict(rec)
    d["duration_s"] = round(rec.ended_at - rec.started_at, 2) if rec.ended_at else ""
    d["dims"] = json.dumps(rec.dims) if rec.dims else ""
    d["governance_events"] = json.dumps(rec.governance_events) if rec.governance_events else ""
    return [d.get(col, "") for col in _EXPORT_CSV_COLUMNS]


def mount_export(app: FastAPI, store: Store) -> None:
    """Mount ``GET /v1/export`` — on-demand run-record export (CSV / JSON)."""

    @app.get("/v1/export")
    def export_runs(
        from_at: float | None = Query(None, description="Start timestamp (epoch seconds)"),
        to_at: float | None = Query(None, description="End timestamp (epoch seconds)"),
        agent: str | None = Query(None, description="Filter by agent name"),
        status: str | None = Query(None, description="Filter by run status"),
        tenant: str | None = Query(None, description="Filter by tenant (from dims)"),
        format: str = Query("json", description="Output format: json or csv"),
        limit: int = Query(5000, ge=1, le=10_000, description="Max rows to return"),
    ) -> Response:
        runs = store.export_runs(
            from_at=from_at,
            to_at=to_at,
            agent=agent,
            status=status,
            tenant=tenant,
            limit=limit,
        )

        if format == "csv":
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(_EXPORT_CSV_COLUMNS)
            for rec in runs:
                writer.writerow(_run_to_csv_row(rec))
            buf.seek(0)
            return StreamingResponse(
                iter([buf.getvalue()]),
                media_type="text/csv",
                headers={"Content-Disposition": 'attachment; filename="export.csv"'},
            )

        # JSON (default)
        rows = [asdict(rec) for rec in runs]
        return JSONResponse(rows, headers={"X-Total-Count": str(len(rows))})


def with_governance_errors(handler: Handler) -> Handler:
    """Wrap a task handler so Halt → 200 halted and Throttled → 429."""

    async def wrapped(
        payload: dict[str, Any],
        headers: Mapping[str, str],
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


def _plane_auth_headers() -> dict[str, str]:
    key = (
        os.environ.get("CONTROL_PLANE_API_KEY") or os.environ.get("TOKENOPS_API_KEY") or ""
    ).strip()
    if not key:
        return {}
    return {"Authorization": f"Bearer {key}"}


async def post_run(
    url: str,
    payload: dict[str, Any],
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """POST ``/v1/runs`` at *url*. Prefer :class:`~tokenops.control.client.ControlPlaneClient`."""
    base = url.rstrip("/")
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(f"{base}/v1/runs", json=payload, headers=_plane_auth_headers())
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
        response = client.post(f"{base}/v1/runs", json=payload, headers=_plane_auth_headers())
        _raise_for_response(response)
        return response.json()
