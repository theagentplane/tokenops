"""The control-plane client: the only place TokenOps does I/O (control plane 1.0).

One small ``httpx`` client over the routes TokenOps uses:

- ``GET /v1/governance/{agent}`` with ``ETag`` / ``If-None-Match``;
- ``POST /v1/ledger/precheck`` and ``POST /v1/ledger/events:batch``;
- ``GET``, ``POST``, ``DELETE /v1/ledger/traces/{trace_id}/halt`` and ``GET /v1/ledger/traces``.

Failure behaviour is explicit, and the client never decides to fail open or closed:

- **Reads** raise :class:`ControlPlaneUnavailable` when the plane cannot be reached, and
  :class:`ControlPlaneError` on any other refusal. The one exception is ``governance``: when the
  plane is unreachable (or answers ``5xx``) and a configuration was already fetched, the last
  known one is returned with ``stale=True``. A ``4xx`` is never masked by the cache.
- **Writes** (``apply_events``, halt mark and clear) are attempted **once**. Events are not
  deduplicated by the plane (control-plane ADR 0007), so this client never retries a write whose
  outcome it does not know. The caller decides what a failed write means.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Mapping
from typing import Any

import httpx

from tokenops.repositories.control_plane_errors import (
    ControlPlaneError,
    ControlPlaneUnavailable,
)
from tokenops.repositories.control_plane_types import (
    ApplyResult,
    GovernanceResult,
    HaltStatus,
    LedgerEvent,
    PrecheckRequest,
    PrecheckResult,
)

URL_ENV = "CONTROL_PLANE_URL"
API_KEY_ENV = "CONTROL_PLANE_API_KEY"
DEFAULT_TIMEOUT_S = 5.0


class ControlPlaneClient:
    """Synchronous client for the control plane's governance and ledger routes."""

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_S,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._base_url = base_url.rstrip("/")
        self._http = httpx.Client(
            base_url=self._base_url, headers=headers, timeout=timeout, transport=transport
        )
        self._lock = threading.Lock()
        self._governance: dict[str, tuple[str | None, dict[str, Any]]] = {}

    @classmethod
    def from_env(cls, **kwargs: Any) -> ControlPlaneClient:
        """Build from ``CONTROL_PLANE_URL`` and ``CONTROL_PLANE_API_KEY``."""
        url = (os.environ.get(URL_ENV) or "").strip()
        if not url:
            raise ControlPlaneError(f"{URL_ENV} is not set")
        key = (os.environ.get(API_KEY_ENV) or "").strip() or None
        return cls(url, api_key=key, **kwargs)

    @property
    def base_url(self) -> str:
        return self._base_url

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> ControlPlaneClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- governance ------------------------------------------------------- #

    def governance(self, agent: str) -> GovernanceResult:
        """The governance dict ``build_governor`` consumes for ``agent`` (``ETag`` cached)."""
        with self._lock:
            cached = self._governance.get(agent)
        headers = {"If-None-Match": cached[0]} if cached and cached[0] else {}
        try:
            response = self._http.get(f"/v1/governance/{agent}", headers=headers)
        except httpx.TransportError as exc:
            return self._stale_or_raise(cached, f"governance for {agent!r}", exc)
        if response.status_code == 304 and cached is not None:
            return GovernanceResult(config=_copy(cached[1]), etag=cached[0])
        if response.status_code >= 500:
            return self._stale_or_raise(cached, f"governance for {agent!r}", response)
        _raise_for_status(response)
        etag = response.headers.get("ETag")
        config = response.json()
        with self._lock:
            self._governance[agent] = (etag, config)
        return GovernanceResult(config=_copy(config), etag=etag)

    def clear_governance_cache(self, agent: str | None = None) -> None:
        """Forget the cached configuration (one agent, or all)."""
        with self._lock:
            if agent is None:
                self._governance.clear()
            else:
                self._governance.pop(agent, None)

    def _stale_or_raise(
        self,
        cached: tuple[str | None, dict[str, Any]] | None,
        what: str,
        cause: BaseException | httpx.Response,
    ) -> GovernanceResult:
        if cached is not None:
            return GovernanceResult(config=_copy(cached[1]), etag=cached[0], stale=True)
        if isinstance(cause, httpx.Response):
            raise ControlPlaneUnavailable(
                f"control plane answered {cause.status_code} for {what}",
                status_code=cause.status_code,
            )
        raise ControlPlaneUnavailable(f"control plane unreachable for {what}: {cause}") from cause

    # ---- ledger reads ------------------------------------------------------ #

    def precheck(self, request: PrecheckRequest) -> PrecheckResult:
        """One read for a pre-call pass: halt, spend and in-flight."""
        body = {
            "trace_id": request.trace_id,
            "segment_keys": request.segment_keys,
            "budgets": request.budgets,
            "want": request.want,
        }
        data = self._send("POST", "/v1/ledger/precheck", json=body).json()
        return PrecheckResult(
            halted=bool(data.get("halted")),
            halt_reason=data.get("halt_reason"),
            spent={str(k): int(v) for k, v in (data.get("spent") or {}).items()},
            inflight={str(k): int(v) for k, v in (data.get("inflight") or {}).items()},
            server_ts=float(data.get("server_ts") or 0.0),
        )

    def halt_status(self, trace_id: str) -> HaltStatus:
        data = self._send("GET", f"/v1/ledger/traces/{trace_id}/halt").json()
        return HaltStatus(halted=bool(data.get("halted")), reason=data.get("halt_reason"))

    def traces(self, *, halted_only: bool = False, limit: int = 100) -> list[dict[str, Any]]:
        """Recent traces joined with halt and spend (the TokenOps run list)."""
        params: dict[str, Any] = {"halted_only": halted_only, "limit": limit}
        data = self._send("GET", "/v1/ledger/traces", params=params).json()
        return list(data.get("traces") or [])

    # ---- ledger writes (attempted once) ----------------------------------- #

    def apply_events(self, events: list[LedgerEvent]) -> ApplyResult:
        """Apply ``events`` in order, in one transaction. Attempted once, never retried."""
        if not events:
            return ApplyResult()
        data = self._send("POST", "/v1/ledger/events:batch", json={"events": events}).json()
        return ApplyResult(
            accepted=int(data.get("accepted") or 0),
            atomic=bool(data.get("atomic", True)),
            totals={str(k): int(v) for k, v in (data.get("totals") or {}).items()},
            halted=bool(data.get("halted")),
        )

    def mark_halted(self, trace_id: str, reason: str = "") -> None:
        self._send("POST", f"/v1/ledger/traces/{trace_id}/halt", json={"reason": reason})

    def clear_halt(self, trace_id: str) -> None:
        self._send("DELETE", f"/v1/ledger/traces/{trace_id}/halt")

    # ---- transport --------------------------------------------------------- #

    def _send(
        self,
        method: str,
        path: str,
        *,
        json: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> httpx.Response:
        try:
            response = self._http.request(method, path, json=json, params=params)
        except httpx.TransportError as exc:
            raise ControlPlaneUnavailable(
                f"control plane unreachable: {method} {path}: {exc}"
            ) from exc
        _raise_for_status(response)
        return response


def _copy(config: dict[str, Any]) -> dict[str, Any]:
    import copy

    return copy.deepcopy(config)


def _error_detail(response: httpx.Response) -> str:
    """The plane's ``detail`` message as a suffix, or ``""`` when the body is not JSON."""
    try:
        body = response.json()
    except ValueError:
        return ""  # a proxy or gateway error page, not the plane's JSON error body
    if isinstance(body, dict) and body.get("detail"):
        return f": {body['detail']}"
    return ""


def _raise_for_status(response: httpx.Response) -> None:
    if response.is_success:
        return
    detail = _error_detail(response)
    kind = ControlPlaneUnavailable if response.status_code >= 500 else ControlPlaneError
    raise kind(
        f"control plane answered {response.status_code}{detail}", status_code=response.status_code
    )
