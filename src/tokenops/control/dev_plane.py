"""Launch a real ``agentplane-control-plane`` in-process, over a real TCP port.

Not part of the public SDK surface. Used by ``tokenops.demo`` (so ``python -m
tokenops.demo`` still needs no external server — tokenops#118 removed the embedded
ledger, so the demo now launches a real, throwaway control plane instead) and by
``tests/conftest.py`` for the live end-to-end tests that need ``ControlPlaneClient``
to talk real HTTP to something (an in-process ASGI ``TestClient`` isn't reachable
by an unrelated ``httpx.Client`` constructed deep inside ``ControlPlaneClient``).

Requires ``agentplane-control-plane`` to be importable — raises ``ImportError``
(caller's problem to handle) when it is not.
"""

from __future__ import annotations

import socket
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class LivePlane:
    url: str
    stop: Callable[[], None]


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def launch(db_path: str, *, startup_timeout: float = 10.0) -> LivePlane:
    """Start a real control-plane FastAPI app on a background thread, over a real
    localhost TCP port. Returns the base URL and a ``stop()`` callback (idempotent
    enough to call once; not designed to be called twice)."""
    import threading

    import uvicorn
    from control_plane.app import create_app
    from control_plane.envelope_store import EnvelopeStore
    from control_plane.settings import Settings
    from control_plane.store import SqliteStore

    store = SqliteStore(db_path, auto_seed=False)
    envelopes = EnvelopeStore(db_path)
    app = create_app(store=store, envelopes=envelopes, settings=Settings(db_path=db_path))

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + startup_timeout
    while not server.started and time.time() < deadline:
        time.sleep(0.02)
    if not server.started:
        raise RuntimeError("control plane did not start within the timeout")

    def stop() -> None:
        server.should_exit = True
        thread.join(timeout=5.0)
        store.close()
        envelopes.close()

    return LivePlane(url=f"http://127.0.0.1:{port}", stop=stop)
