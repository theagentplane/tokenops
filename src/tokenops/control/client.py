"""SDK client for the TokenOps control plane.

Prefer :class:`ControlPlaneClient` over posting ``/v1/runs`` at an agent URL.
When ``TOKENOPS_URL`` is set, registration (and future plane APIs) go over HTTP.
When ``TOKENOPS_EMBEDDED=1`` or no URL is set, the client uses an in-process
:class:`~tokenops.control.store.Store` (shared SQLite via ``TOKENOPS_DB``).
"""

from __future__ import annotations

import os
from typing import Any, Mapping

from tokenops.control.http import post_run, post_run_sync
from tokenops.control.models import (
    GovernanceMode,
    RunAlreadyRegisteredError,
    RunRegistration,
    parse_governance_mode,
)
from tokenops.control.store import Store, new_id


def _coerce_user_dims(raw: Mapping[str, Any] | None) -> dict[str, str]:
    if not raw:
        return {}
    return {str(k): str(v) for k, v in raw.items()}


def _mode_value(mode: GovernanceMode | str | None) -> GovernanceMode:
    if mode is None or mode == "":
        return GovernanceMode.ENFORCE
    if isinstance(mode, GovernanceMode):
        return mode
    return parse_governance_mode(mode)


class ControlPlaneClient:
    """Talk to a remote control plane or an embedded Store."""

    def __init__(
        self,
        *,
        url: str | None = None,
        store: Store | None = None,
        timeout: float = 30.0,
    ) -> None:
        if bool(url) == bool(store):
            raise ValueError("exactly one of url or store is required")
        self._url = url.rstrip("/") if url else None
        self._store = store
        self._timeout = timeout

    @classmethod
    def from_env(cls, *, timeout: float = 30.0) -> ControlPlaneClient:
        """Build a client from ``TOKENOPS_URL`` / ``TOKENOPS_EMBEDDED`` / ``TOKENOPS_DB``.

        * ``TOKENOPS_URL`` set and ``TOKENOPS_EMBEDDED`` not ``1`` → HTTP to the plane.
        * otherwise → embedded :class:`Store` at ``TOKENOPS_DB`` (default ``tokenops.db``).
        """
        embedded = os.environ.get("TOKENOPS_EMBEDDED", "").strip() == "1"
        url = (os.environ.get("TOKENOPS_URL") or "").strip()
        if url and not embedded:
            return cls(url=url, timeout=timeout)
        db = os.environ.get("TOKENOPS_DB", "tokenops.db")
        return cls(store=Store(db), timeout=timeout)

    @property
    def url(self) -> str | None:
        return self._url

    @property
    def embedded(self) -> bool:
        return self._store is not None

    def register_run(
        self,
        *,
        intent: str = "",
        user_dims: Mapping[str, Any] | None = None,
        mode: GovernanceMode | str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Register a run; returns ``{run_id, status, mode}`` (same shape as ``POST /v1/runs``)."""
        dims = _coerce_user_dims(user_dims)
        gov_mode = _mode_value(mode)
        if self._store is not None:
            rid = (run_id or "").strip() or new_id("run")
            try:
                reg = self._store.register_run(
                    RunRegistration(
                        run_id=rid, intent=intent, user_dims=dims, mode=gov_mode,
                    )
                )
            except RunAlreadyRegisteredError:
                raise
            return {
                "run_id": reg.run_id,
                "status": "registered",
                "mode": reg.mode.value,
            }
        assert self._url is not None
        payload: dict[str, Any] = {
            "intent": intent,
            "user_dims": dims,
            "mode": gov_mode.value,
        }
        if run_id:
            payload["run_id"] = run_id
        return post_run_sync(self._url, payload, timeout=self._timeout)

    async def register_run_async(
        self,
        *,
        intent: str = "",
        user_dims: Mapping[str, Any] | None = None,
        mode: GovernanceMode | str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Async variant of :meth:`register_run` (HTTP path only uses async httpx)."""
        dims = _coerce_user_dims(user_dims)
        gov_mode = _mode_value(mode)
        if self._store is not None:
            return self.register_run(
                intent=intent, user_dims=dims, mode=gov_mode, run_id=run_id,
            )
        assert self._url is not None
        payload: dict[str, Any] = {
            "intent": intent,
            "user_dims": dims,
            "mode": gov_mode.value,
        }
        if run_id:
            payload["run_id"] = run_id
        return await post_run(self._url, payload, timeout=self._timeout)


def should_mount_run_registration() -> bool:
    """Whether an agent app should expose ``POST /v1/runs``.

    When ``TOKENOPS_URL`` points at a standalone plane (and embedded mode is off),
    registration is centralized on the plane — agents must not mount the route.
    """
    if os.environ.get("TOKENOPS_EMBEDDED", "").strip() == "1":
        return True
    return not (os.environ.get("TOKENOPS_URL") or "").strip()
