"""SDK client for the TokenOps control plane.

Prefer :class:`ControlPlaneClient` over posting ``/v1/runs`` at an agent URL.
When ``TOKENOPS_URL`` is set, registration (and future plane APIs) go over HTTP.
When ``TOKENOPS_EMBEDDED=1`` or no URL is set, the client uses an in-process
:class:`~tokenops.control.store.Store` (shared SQLite via ``TOKENOPS_DB``).

Agents should talk to the plane through this client (§6) — do not construct
``Store(TOKENOPS_DB)`` on the happy path. ``require_store()`` is an escape hatch
for ledger / dashboard rows until those APIs are fully remote.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any, cast

from tokenops.control.http import post_run, post_run_sync
from tokenops.control.http_store import HttpStore
from tokenops.control.models import (
    GovernanceMode,
    RunAlreadyRegisteredError,
    RunRecord,
    RunRegistration,
    parse_governance_mode,
)
from tokenops.control.store import Store, new_id

logger = logging.getLogger("tokenops.client")


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
        self._hybrid_store: Any = None
        self._timeout = timeout

    @classmethod
    def from_env(cls, *, timeout: float = 30.0) -> ControlPlaneClient:
        """Build a client from ``TOKENOPS_URL`` / ``TOKENOPS_EMBEDDED`` / ``TOKENOPS_DB``.

        * ``TOKENOPS_URL`` or ``CONTROL_PLANE_URL`` set and ``TOKENOPS_EMBEDDED`` not ``1``
          → HTTP to the plane (no local SQLite).
        * otherwise → embedded :class:`Store` at ``TOKENOPS_DB``.
        """
        from tokenops.control.crossing import install_crossing_hook

        install_crossing_hook()
        embedded = os.environ.get("TOKENOPS_EMBEDDED", "").strip() == "1"
        url = (
            os.environ.get("CONTROL_PLANE_URL")
            or os.environ.get("TOKENOPS_URL")
            or os.environ.get("TOKENOPS_CONTROL_PLANE_URL")
            or ""
        ).strip()
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

    @property
    def store(self) -> Store | None:
        """Embedded registration Store, or ``None`` when registration is remote.

        Prefer :meth:`governance_config_for`, :meth:`resolve_run`, and
        :meth:`require_store` over using this directly. Escape hatch only (§6).
        """
        return self._store

    def require_store(self) -> Store:
        """Backing store for ledger / config / dashboard rows.

        Embedded mode returns the in-process SQLite Store. Remote mode returns
        :class:`HttpStore` — never a local DB file.
        """
        if self._store is not None:
            return self._store
        if self._hybrid_store is None:
            assert self._url is not None
            key = os.environ.get("CONTROL_PLANE_API_KEY") or os.environ.get("TOKENOPS_API_KEY")
            self._hybrid_store = HttpStore(self._url, api_key=key, timeout=self._timeout)
        return cast(Store, self._hybrid_store)

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
                        run_id=rid,
                        intent=intent,
                        user_dims=dims,
                        mode=gov_mode,
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
                intent=intent,
                user_dims=dims,
                mode=gov_mode,
                run_id=run_id,
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

    def resolve_run(self, run_id: str) -> RunRegistration:
        """Resolve a registered run (embedded Store or shared ``TOKENOPS_DB``)."""
        return self.require_store().resolve_run(run_id)

    def governance_config_for(self, agent: str) -> dict:
        """Governance config dict for ``build_governor`` (process-cached; §10)."""
        return self.require_store().governance_config_for(agent)

    def create_run(self, rec: RunRecord) -> RunRecord:
        """Dashboard run row — escape hatch until plane HTTP covers this."""
        return self.require_store().create_run(rec)

    def update_run(self, run_id: str, **fields: Any) -> None:
        """Update a dashboard run row — escape hatch until plane HTTP covers this."""
        self.require_store().update_run(run_id, **fields)


def should_mount_run_registration() -> bool:
    """Whether an agent app should expose ``POST /v1/runs``.

    When ``TOKENOPS_URL`` points at a standalone plane (and embedded mode is off),
    registration is centralized on the plane — agents must not mount the route.
    """
    if os.environ.get("TOKENOPS_EMBEDDED", "").strip() == "1":
        return True
    return not (os.environ.get("TOKENOPS_URL") or "").strip()
