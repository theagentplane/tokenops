"""In-memory :class:`~tokenops.control.ledger_backend.LedgerBackend` for unit tests.

Mirrors the control-plane semantics (in-order apply, per-tenant idempotency dedup,
``totals`` in the ack). Kept honest by ``test_ledger_backend_contract.py``, which runs
the same assertions against this and the real plane over ``httpx.ASGITransport``.

``.trip()`` / ``.heal()`` / ``.fail_next()`` drive the plane-unreachable tests.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from tokenops.control.ledger_backend import (
    AggregateState,
    ApplyResult,
    LedgerEvent,
    PrecheckRequest,
)
from tokenops.control.models import (
    GovernanceMode,
    RunAlreadyRegisteredError,
    RunNotRegisteredError,
    RunRegistration,
    parse_governance_mode,
)

_RUN_STATE_WINDOW = 64


class PlaneUnreachable(RuntimeError):
    """Raised by a tripped FakeLedgerBackend, mimicking an httpx transport error."""


class FakeLedgerBackend:
    def __init__(self, *, governance: dict[str, Any] | None = None) -> None:
        self._spent: dict[tuple[str, str, str], int] = {}
        self._inflight: dict[str, int] = {}
        self._halt: dict[str, tuple[bool, str | None]] = {}
        self._regs: dict[str, RunRegistration] = {}
        self._reg_at: dict[str, float] = {}
        self._run_state: dict[str, dict[str, Any]] = {}
        self._seen: set[str] = set()
        self._records: dict[str, dict[str, Any]] = {}
        self._governance = governance or {"governance": {"budgets": [], "policies": {}}}
        # fault injection
        self._tripped = False
        self._fail_next = 0

    # ---- fault injection -------------------------------------------------- #

    def trip(self) -> None:
        self._tripped = True

    def heal(self) -> None:
        self._tripped = False
        self._fail_next = 0

    def fail_next(self, n: int) -> None:
        self._fail_next = n

    def _guard(self) -> None:
        if self._tripped:
            raise PlaneUnreachable("plane unreachable (tripped)")
        if self._fail_next > 0:
            self._fail_next -= 1
            raise PlaneUnreachable("plane unreachable (transient)")

    # ---- LedgerBackend ------------------------------------------------- #

    def close(self) -> None:  # noqa: D401 - parity with HttpLedgerBackend
        return None

    def read_state(self, req: PrecheckRequest) -> AggregateState:
        self._guard()
        out = AggregateState(server_ts=time.time())
        if "halt" in req.want:
            halted, reason = self._halt.get(req.trace_id, (False, None))
            out.halted, out.halt_reason = halted, reason
        if "spent" in req.want:
            out.spent = {
                f"{b['budget_id']}|{b['segment_key']}|{b.get('period', 'lifetime')}": self._spent.get(
                    (b["budget_id"], b["segment_key"], b.get("period", "lifetime")), 0
                )
                for b in req.budgets
            }
        if "inflight" in req.want:
            out.inflight = {s: self._inflight.get(s, 0) for s in req.segment_keys}
        if "window" in req.want:
            st = self._run_state.get(req.trace_id)
            out.window = (
                {
                    "step_count": st["step_count"],
                    "recent": st["recent"],
                    "velocity_micros_per_step": st["velocity_micros_per_step"],
                }
                if st
                else {"step_count": 0, "recent": [], "velocity_micros_per_step": 0.0}
            )
        return out

    def apply_events(self, events: list[LedgerEvent], *, durability: str = "sync") -> ApplyResult:
        self._guard()
        if not events:
            return ApplyResult()
        accepted = deduped = 0
        touched: set[tuple[str, str, str]] = set()
        trace_ids: set[str] = set()
        for ev in events:
            key = str(ev.get("idempotency_key") or "").strip()
            if not key:
                raise ValueError("event missing idempotency_key")
            if ev.get("kind") == "spent_add":
                for t in ev.get("targets") or []:
                    touched.add((t["budget_id"], t["segment_key"], t.get("period", "lifetime")))
            if ev.get("trace_id"):
                trace_ids.add(str(ev["trace_id"]))
            if key in self._seen:
                deduped += 1
                continue
            self._apply_one(ev)
            self._seen.add(key)
            accepted += 1
        totals = {f"{b}|{s}|{p}": self._spent.get((b, s, p), 0) for (b, s, p) in touched}
        halted = any(self._halt.get(r, (False, None))[0] for r in trace_ids)
        return ApplyResult(accepted=accepted, deduped=deduped, totals=totals, halted=halted)

    def _apply_one(self, ev: LedgerEvent) -> None:
        kind = ev.get("kind")
        trace_id = str(ev.get("trace_id") or "")
        if kind == "spent_add":
            delta = int(ev.get("delta_micros", 0))
            for t in ev.get("targets") or []:
                k = (t["budget_id"], t["segment_key"], t.get("period", "lifetime"))
                self._spent[k] = self._spent.get(k, 0) + delta
        elif kind == "admit":
            s = ev["segment_key"]
            self._inflight[s] = self._inflight.get(s, 0) + 1
        elif kind == "complete":
            s = ev["segment_key"]
            self._inflight[s] = max(0, self._inflight.get(s, 0) - 1)
        elif kind == "step":
            st = self._run_state.setdefault(
                trace_id, {"step_count": 0, "recent": [], "velocity_micros_per_step": 0.0}
            )
            st["recent"] = (
                st["recent"]
                + [
                    {
                        k: ev.get(k)
                        for k in (
                            "agent",
                            "seq",
                            "node_type",
                            "boundary_id",
                            "cost_micros",
                            "cum_spent_micros",
                            "usage",
                            "tags",
                            "tool_signature",
                            "result_hash",
                            "ts",
                            "compaction",
                        )
                        if ev.get(k) is not None
                    }
                ]
            )[-_RUN_STATE_WINDOW:]
            st["step_count"] += 1
            win = st["recent"]
            st["velocity_micros_per_step"] = (
                (win[-1].get("cum_spent_micros", 0) - win[0].get("cum_spent_micros", 0))
                / (len(win) - 1)
                if len(win) >= 2
                else 0.0
            )
        elif kind == "halt_mark":
            self._halt[trace_id] = (True, ev.get("reason") or None)
            if trace_id in self._records:
                self._records[trace_id]["status"] = "halted"
        elif kind == "halt_clear":
            self._halt[trace_id] = (False, None)
        else:
            raise ValueError(f"unknown event kind {kind!r}")

    def register_run(
        self,
        *,
        intent: str = "",
        user_dims: dict[str, str] | None = None,
        mode: GovernanceMode | str | None = None,
        trace_id: str | None = None,
    ) -> RunRegistration:
        self._guard()
        rid = (trace_id or "").strip() or f"run_{uuid.uuid4().hex[:8]}"
        if rid in self._regs:
            raise RunAlreadyRegisteredError(f"run {rid!r} is already registered")
        reg = RunRegistration(
            trace_id=rid,
            intent=intent,
            user_dims={str(k): str(v) for k, v in (user_dims or {}).items()},
            mode=parse_governance_mode(mode) if mode not in (None, "") else GovernanceMode.ENFORCE,
        )
        self._regs[rid] = reg
        self._reg_at[rid] = time.time()
        self._records[rid] = {"trace_id": rid, "agent": intent or "agent", "status": "running"}
        return reg

    def resolve_run(self, trace_id: str) -> RunRegistration:
        self._guard()
        try:
            return self._regs[trace_id]
        except KeyError:
            raise RunNotRegisteredError(f"run {trace_id!r} is not registered") from None

    def governance_config_for(self, agent: str) -> dict[str, Any]:
        self._guard()
        return self._governance

    def patch_run_record(self, trace_id: str, **fields: Any) -> None:
        self._guard()
        rec = self._records.setdefault(trace_id, {"trace_id": trace_id})
        for k, v in fields.items():
            if k in ("steps", "cost_micros"):
                continue
            rec[k] = v
