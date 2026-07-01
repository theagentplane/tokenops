"""Open the configured control-store backend (local SQLite or remote HTTP)."""

from __future__ import annotations

import os

from tokenops.control.remote_store import RemoteStore
from tokenops.control.store import SqliteStore
from tokenops.control.store_protocol import ControlStore


def control_plane_url() -> str | None:
    url = os.environ.get("TOKENOPS_CONTROL_PLANE_URL", "").strip()
    return url.rstrip("/") if url else None


def open_store(*, auto_seed: bool = True, db: str | None = None) -> ControlStore:
    """Return a store handle for the active backend.

  * ``TOKENOPS_CONTROL_PLANE_URL`` set → :class:`RemoteStore` (HTTP; no direct SQLite).
  * otherwise → :class:`SqliteStore` at ``TOKENOPS_DB`` (default ``tokenops.db``).
    """
    remote = control_plane_url()
    if remote:
        return RemoteStore(remote)
    path = db or os.environ.get("TOKENOPS_DB", "tokenops.db")
    return SqliteStore(path, auto_seed=auto_seed)


def registration_base_url(agent_url: str) -> str:
    """URL for ``POST /v1/runs`` — control plane when split, else the entry agent."""
    return control_plane_url() or agent_url.rstrip("/")
