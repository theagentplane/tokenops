"""SDK client for the TokenOps control plane.

``ControlPlaneClient`` is the only supported way a live agent reaches the plane —
``from_env()`` requires ``CONTROL_PLANE_URL`` / ``TOKENOPS_URL`` and raises if neither
is set. There is no embedded / local-file fallback: tokenops has no ledger of its own
(tokenops#118, the remote-only rewrite) — every spend/inflight/halt read or write goes
to the control plane over HTTP via :meth:`backend` (a
:class:`~tokenops.control.ledger_backend.LedgerBackend`), and registration/governance
config/dashboard rows go through :class:`~tokenops.control.http_store.HttpStore`. Both
are HTTP-only; neither ever opens a local SQLite file.

The ``store=`` constructor kwarg is a explicit, visible test-only escape hatch (dependency
injection for unit/integration tests that want to exercise policy logic against a local
:class:`~tokenops.control.store.Store` without a running plane) — it is never reachable
from ``from_env()``, so no environment misconfiguration can silently select it.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any, cast

import httpx

from tokenops.control.http import post_run, post_run_sync
from tokenops.control.http_store import HttpStore
from tokenops.control.ledger_backend import HttpLedgerBackend, LedgerBackend
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
    """Talk to the remote control plane over HTTP (or, in tests only, a local Store)."""

    def __init__(
        self,
        *,
        url: str | None = None,
        store: Store | None = None,
        timeout: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        if bool(url) == bool(store):
            raise ValueError("exactly one of url or store is required")
        self._url = url.rstrip("/") if url else None
        self._store = store
        self._hybrid_store: Any = None
        self._backend: LedgerBackend | None = None
        self._timeout = timeout
        self._client = client  # optional injected httpx.Client — tests only

    @classmethod
    def from_env(cls, *, timeout: float = 30.0) -> ControlPlaneClient:
        """Build a client from ``CONTROL_PLANE_URL`` / ``TOKENOPS_URL``.

        Raises if neither is set — tokenops has no embedded / local-file ledger to fall
        back to (tokenops#118). Point this at a running control plane: ``control-plane
        serve`` locally, or the Docker image, for anything other than tests that pass
        ``store=`` explicitly.
        """
        from tokenops.control.crossing import install_crossing_hook

        install_crossing_hook()
        url = (
            os.environ.get("CONTROL_PLANE_URL")
            or os.environ.get("TOKENOPS_URL")
            or os.environ.get("TOKENOPS_CONTROL_PLANE_URL")
            or ""
        ).strip()
        if not url:
            raise RuntimeError(
                "CONTROL_PLANE_URL (or TOKENOPS_URL) is required — tokenops has no "
                "embedded/local ledger; point it at a running control plane. Run "
                "`control-plane serve` locally (see the agentplane-control-plane "
                "package) or use its Docker image, then set CONTROL_PLANE_URL to it."
            )
        return cls(url=url, timeout=timeout)

    @property
    def url(self) -> str | None:
        return self._url

    @property
    def embedded(self) -> bool:
        """``True`` only for the explicit test-only ``store=`` constructor path.

        Never ``True`` for a client built by :meth:`from_env` — there is no
        environment variable that selects a local ledger.
        """
        return self._store is not None

    @property
    def store(self) -> Store | None:
        """The explicit test-only local Store, or ``None`` in the (only production)
        remote mode. Prefer :meth:`backend`, :meth:`governance_config_for`, and
        :meth:`resolve_run` over using this directly."""
        return self._store

    @property
    def backend(self) -> LedgerBackend:
        """The :class:`~tokenops.control.ledger_backend.LedgerBackend` for this client
        — every spend/inflight/halt read (``precheck``) and write (``events:batch``)
        goes through this. Only valid in remote mode (``from_env()`` always is)."""
        if self._url is None:
            raise RuntimeError(
                "no LedgerBackend for a store=-constructed (test-only) ControlPlaneClient"
            )
        if self._backend is None:
            key = os.environ.get("CONTROL_PLANE_API_KEY") or os.environ.get("TOKENOPS_API_KEY")
            self._backend = HttpLedgerBackend(
                self._url, api_key=key, timeout=self._timeout, client=self._client
            )
        return self._backend

    def require_store(self) -> Store:
        """Registration / governance-config / dashboard-row transport.

        The test-only ``store=`` path returns that Store. Remote mode (``from_env()``)
        returns :class:`HttpStore` — HTTP only, never a local DB file. Ledger accounting
        (spend/inflight/halt) does **not** go through this — see :meth:`backend`.
        """
        if self._store is not None:
            return self._store
        if self._hybrid_store is None:
            assert self._url is not None
            key = os.environ.get("CONTROL_PLANE_API_KEY") or os.environ.get("TOKENOPS_API_KEY")
            self._hybrid_store = HttpStore(
                self._url, api_key=key, timeout=self._timeout, client=self._client
            )
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

    Always ``False`` — registration is centralized on the plane (tokenops#118); there
    is no embedded mode left for an agent to self-host it under. Kept (rather than
    deleted outright) so existing ``if should_mount_run_registration(): ...`` call
    sites keep working unchanged while they're cleaned up.
    """
    return False
