"""A real control plane 1.x in process (SQLite, free localhost port) for end-to-end tests.

The same HTTP API a deployed plane serves. Start it with ``with LocalPlane() as plane:``;
Chronicle is pointed at it for the block, and the plane's governance is configured through its
own ``PUT /v1/budgets`` and ``PUT /v1/policies`` routes.
"""

from __future__ import annotations

import asyncio
import gc
import shutil
import socket
import tempfile
import threading
import time
from pathlib import Path
from types import TracebackType
from typing import Any

import chronicle
import httpx

API_KEY = "e2e-key"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}


class _SerializeRequests:
    """Handle one HTTP request at a time.

    The plane's SQLite file cannot upgrade a read transaction to a write one under concurrent
    writers (``database is locked``, answered as a ``500``). A TokenOps agent writes ledger
    events while Chronicle delivers envelopes, so the test plane serializes requests. A
    deployment uses a database that supports concurrent writers.
    """

    def __init__(self, app: Any) -> None:
        self._app = app
        self._lock = asyncio.Lock()

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        async with self._lock:
            await self._app(scope, receive, send)


class LocalPlane:
    def __init__(self) -> None:
        import uvicorn
        from control_plane.api import create_app
        from control_plane.settings import Settings

        self._dir = tempfile.mkdtemp(prefix="tokenops-e2e-")
        url = f"sqlite:///{(Path(self._dir) / 'plane.db').as_posix()}"
        settings = Settings(
            database_url=url, api_keys=f"{API_KEY}:e2e:ingest+read+admin", seed_on_start=False
        )
        self._app = create_app(settings)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self.port: int = self._sock.getsockname()[1]
        self._server = uvicorn.Server(
            uvicorn.Config(
                _SerializeRequests(self._app),
                log_level="warning",
                lifespan="off",
                access_log=False,
            )
        )
        self._thread = threading.Thread(
            target=lambda: self._server.run(sockets=[self._sock]), daemon=True
        )

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> LocalPlane:
        self._thread.start()
        deadline = time.monotonic() + 15
        while not self._server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("the control plane did not start")
            time.sleep(0.02)
        chronicle.configure(
            control_plane_url=self.url,
            api_key=API_KEY,
            service_name="e2e",
            batch_size=10,
            flush_interval=0.05,
        )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        chronicle.flush()
        chronicle.reset()
        self._server.should_exit = True
        self._thread.join(timeout=5)
        self._sock.close()
        self._app.state.cp.engine.dispose()
        gc.collect()
        shutil.rmtree(self._dir, ignore_errors=True)

    # ---- plane API --------------------------------------------------------- #

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        with httpx.Client(base_url=self.url, headers=HEADERS, timeout=10) as http:
            response = http.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()

    def configure_cost_cap(self, limit_micros: int, *, budget_id: str = "run_llm_cap") -> None:
        """One budget per trace and a ``cost_budget`` policy on it, written through the API."""
        self.request(
            "PUT",
            "/v1/budgets",
            json={"id": budget_id, "limit_micros": limit_micros, "dimension": "trace"},
        )
        self.request(
            "PUT",
            "/v1/policies",
            json={
                "id": "cap",
                "template": "cost_budget",
                "budget_id": budget_id,
                "params": {"budget": budget_id},
            },
        )

    def trace(self, trace_id: str) -> dict[str, Any]:
        return self.request("GET", f"/v1/traces/{trace_id}")

    def wait_for_trace(self, trace_id: str, timeout: float = 10.0) -> dict[str, Any]:
        """Flush Chronicle, then wait until the trace is readable."""
        deadline = time.monotonic() + timeout
        while True:
            chronicle.flush()
            try:
                return self.trace(trace_id)
            except httpx.HTTPStatusError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.05)
