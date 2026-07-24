"""FastAPI control-plane application (registration + health; observe later)."""

from __future__ import annotations

import os

from fastapi import FastAPI

from tokenops import __version__
from tokenops.control.http import mount_run_registration
from tokenops.control.store import Store


def create_app(store: Store | None = None) -> FastAPI:
    """Build the control-plane app.

    Owns a :class:`Store` and mounts:

    * ``POST /v1/runs`` — run registration (intent, user_dims, mode)
    * ``GET /health`` — liveness

    Future routes (observe / governance remote) can mount here without changing
    agent SDKs beyond pointing ``TOKENOPS_URL`` at this service.
    """
    store = store or Store(os.environ.get("TOKENOPS_DB", "tokenops.db"))

    app = FastAPI(title="TokenOps Control Plane", version=__version__)
    app.state.store = store

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "tokenops-control-plane"}

    mount_run_registration(app, store)

    # Placeholder for future plane APIs (observe, governance admin over HTTP, etc.).
    # Agents keep using ControlPlaneClient; expand the plane surface here.

    return app
