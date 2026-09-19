"""LedgerBackend — the single interface the SDK uses to reach the control plane.

The remote-only rewrite (see the ``remote-only control plane`` epic) routes every
ledger read/write through this protocol. There is one implementation:

* :class:`HttpLedgerBackend` — direct ``httpx`` to a running plane. Production, and in
  tests too: they drive it against a real in-process ``control_plane.app``, not a fake,
  so the SDK and the plane cannot drift (see ``docs/testing.md``).

**The only write path is :meth:`apply_events`** — a list of :class:`LedgerEvent`. A
future ``BufferedLedgerBackend`` wraps an inner backend and coalesces those calls
without any call site changing.

Wire contract: ``agentplane-control-plane`` ``docs/api-contract.md`` (0.2.0).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Protocol, TypedDict, runtime_checkable

import httpx

from tokenops.control.models import (
    GovernanceMode,
    RunAlreadyRegisteredError,
    RunNotRegisteredError,
    RunRegistration,
    parse_governance_mode,
)

# --------------------------------------------------------------------------- #
# Event + result shapes (JSON-aligned with the wire contract)                 #
# --------------------------------------------------------------------------- #


class LedgerEvent(TypedDict, total=False):
    """One ledger mutation. ``kind`` + ``idempotency_key`` are always required.

    kinds: ``spent_add`` · ``admit`` · ``complete`` · ``step`` · ``halt_mark`` ·
    ``halt_clear``. See contract §5.
    """

    kind: str
    idempotency_key: str
    ts: float
    run_id: str
    # spent_add
    delta_micros: int
    targets: list[dict[str, Any]]  # [{budget_id, segment_key, period}]
    # admit / complete
    segment_key: str
    # step
    agent: str
    seq: int
    node_type: str
    boundary_id: str
    cost_micros: int
    cum_spent_micros: int
    usage: dict[str, int]
    tags: dict[str, str]
    tool_signature: str
    result_hash: str
    # compaction
    compaction: dict[str, int]
    # halt_mark
    reason: str
    detector: str


@dataclass(kw_only=True)
class PrecheckRequest:
    run_id: str
    segment_keys: list[str] = field(default_factory=list)
    budgets: list[dict[str, str]] = field(
        default_factory=list
    )  # [{budget_id, segment_key, period}]
    want: list[str] = field(default_factory=lambda: ["spent", "inflight", "halt"])


@dataclass
class AggregateState:
    server_ts: float = 0.0
    halted: bool = False
    halt_reason: str | None = None
    spent: dict[str, int] = field(
        default_factory=dict
    )  # "<budget_id>|<segment_key>|<period>" -> micros
    inflight: dict[str, int] = field(default_factory=dict)  # segment_key -> count
    window: dict[str, Any] | None = None  # {step_count, recent, velocity_micros_per_step}


@dataclass
class ApplyResult:
    accepted: int = 0
    deduped: int = 0
    totals: dict[str, int] = field(default_factory=dict)
    halted: bool = False


# --------------------------------------------------------------------------- #
# Protocol                                                                    #
# --------------------------------------------------------------------------- #


@runtime_checkable
class LedgerBackend(Protocol):
    """Everything the SDK needs from the control plane."""

    def read_state(self, req: PrecheckRequest) -> AggregateState: ...

    def apply_events(
        self, events: list[LedgerEvent], *, durability: str = "sync"
    ) -> ApplyResult: ...

    def register_run(
        self,
        *,
        intent: str = "",
        user_dims: dict[str, str] | None = None,
        mode: GovernanceMode | str | None = None,
        run_id: str | None = None,
    ) -> RunRegistration: ...

    def resolve_run(self, run_id: str) -> RunRegistration: ...

    def governance_config_for(self, agent: str) -> dict[str, Any]: ...

    def patch_run_record(self, run_id: str, **fields: Any) -> None: ...

    def close(self) -> None: ...


def _mode_value(mode: GovernanceMode | str | None) -> GovernanceMode:
    if mode is None or mode == "":
        return GovernanceMode.ENFORCE
    if isinstance(mode, GovernanceMode):
        return mode
    return parse_governance_mode(mode)


def _reg_from_body(body: dict[str, Any], *, fallback_intent: str = "") -> RunRegistration:
    return RunRegistration(
        run_id=str(body["run_id"]),
        intent=str(body.get("intent") or fallback_intent),
        user_dims={str(k): str(v) for k, v in (body.get("user_dims") or {}).items()},
        mode=parse_governance_mode(body.get("mode")),
    )


# --------------------------------------------------------------------------- #
# HTTP implementation                                                         #
# --------------------------------------------------------------------------- #


class HttpLedgerBackend:
    """:class:`LedgerBackend` over the control-plane HTTP API."""

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._owns_client = client is None
        key = (
            api_key or os.environ.get("CONTROL_PLANE_API_KEY") or os.environ.get("TOKENOPS_API_KEY")
        )
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        self._client = client or httpx.Client(
            base_url=self._base_url, timeout=timeout, headers=headers
        )

    # ---- lifecycle ----------------------------------------------------------

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _req(self, method: str, path: str, **kw: Any) -> httpx.Response:
        r = self._client.request(method, path, **kw)
        if r.status_code == 409:
            raise RunAlreadyRegisteredError(_err(r, "run already registered"))
        r.raise_for_status()
        return r

    # ---- reads ------------------------------------------------------------- #

    def read_state(self, req: PrecheckRequest) -> AggregateState:
        r = self._req(
            "POST",
            "/v1/ledger/precheck",
            json={
                "run_id": req.run_id,
                "segment_keys": req.segment_keys,
                "budgets": req.budgets,
                "want": req.want,
            },
        )
        b = r.json()
        return AggregateState(
            server_ts=float(b.get("server_ts") or 0.0),
            halted=bool(b.get("halted")),
            halt_reason=b.get("halt_reason"),
            spent={str(k): int(v) for k, v in (b.get("spent") or {}).items()},
            inflight={str(k): int(v) for k, v in (b.get("inflight") or {}).items()},
            window=b.get("window"),
        )

    def resolve_run(self, run_id: str) -> RunRegistration:
        r = self._client.get(f"/v1/runs/{run_id}/registration")
        if r.status_code == 404:
            raise RunNotRegisteredError(f"run {run_id!r} is not registered")
        r.raise_for_status()
        return _reg_from_body(r.json())

    def governance_config_for(self, agent: str) -> dict[str, Any]:
        return self._req("GET", f"/v1/governance/{agent}").json()

    # ---- writes ---------------------------------------------------------- #

    def apply_events(self, events: list[LedgerEvent], *, durability: str = "sync") -> ApplyResult:
        # TODO(buffering): a BufferedLedgerBackend wraps this backend and coalesces
        # apply_events into a background flush so a governed LLM call costs 1 sync
        # round trip instead of 2. See the remote-only plan Part 7 / Phase 4.
        if not events:
            return ApplyResult()
        r = self._req(
            "POST",
            "/v1/ledger/events:batch",
            json={"events": events},
            headers={"Durability": durability},
        )
        b = r.json()
        return ApplyResult(
            accepted=int(b.get("accepted") or 0),
            deduped=int(b.get("deduped") or 0),
            totals={str(k): int(v) for k, v in (b.get("totals") or {}).items()},
            halted=bool(b.get("halted")),
        )

    def register_run(
        self,
        *,
        intent: str = "",
        user_dims: dict[str, str] | None = None,
        mode: GovernanceMode | str | None = None,
        run_id: str | None = None,
    ) -> RunRegistration:
        payload: dict[str, Any] = {
            "intent": intent,
            "user_dims": {str(k): str(v) for k, v in (user_dims or {}).items()},
            "mode": _mode_value(mode).value,
        }
        if run_id:
            payload["run_id"] = run_id
        r = self._req("POST", "/v1/runs", json=payload)
        return _reg_from_body(r.json(), fallback_intent=intent)

    def patch_run_record(self, run_id: str, **fields: Any) -> None:
        # steps / cost_micros are derived server-side; the plane ignores them (0.2.x)
        # and rejects them (0.3.0). Don't send them.
        clean = {k: v for k, v in fields.items() if k not in ("steps", "cost_micros")}
        if not clean:
            return
        self._req("PATCH", f"/v1/run-records/{run_id}", json=clean)


def _err(r: httpx.Response, default: str) -> str:
    try:
        body = r.json()
        return str(body.get("error") or body.get("detail") or default)
    except Exception:
        return default
