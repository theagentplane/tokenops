"""HTTP-backed Store used when TOKENOPS_URL / CONTROL_PLANE_URL is set.

Does not open SQLite. All ledger, governance, and run-history traffic goes to
the control plane process.
"""

from __future__ import annotations

from typing import Any

import httpx

from tokenops.control.models import (
    BudgetSpec,
    PolicyInstance,
    RunAlreadyRegisteredError,
    RunNotRegisteredError,
    RunRecord,
    RunRegistration,
    Segment,
    parse_governance_mode,
)


class HttpStore:
    def __init__(self, base_url: str, *, api_key: str | None = None, timeout: float = 30.0) -> None:
        self.path = base_url.rstrip("/")
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.Client(base_url=self.path, timeout=timeout, headers=headers)

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        response = self._client.request(method, path, **kwargs)
        if response.status_code == 409:
            body = response.json()
            raise RunAlreadyRegisteredError(body.get("error", "run already registered"))
        if response.status_code == 404:
            return response
        response.raise_for_status()
        return response

    def register_run(self, reg: RunRegistration) -> RunRegistration:
        r = self._request(
            "POST",
            "/v1/runs",
            json={
                "run_id": reg.run_id,
                "intent": reg.intent,
                "user_dims": dict(reg.user_dims),
                "mode": reg.mode.value,
            },
        )
        body = r.json()
        return RunRegistration(
            run_id=str(body["run_id"]),
            intent=str(body.get("intent") or reg.intent),
            user_dims={str(k): str(v) for k, v in (body.get("user_dims") or reg.user_dims).items()},
            mode=parse_governance_mode(body.get("mode") or reg.mode),
        )

    def resolve_run(self, run_id: str) -> RunRegistration:
        r = self._client.get(f"/v1/runs/{run_id}/registration")
        if r.status_code == 404:
            raise RunNotRegisteredError(f"run {run_id!r} is not registered")
        r.raise_for_status()
        body = r.json()
        return RunRegistration(
            run_id=str(body["run_id"]),
            intent=str(body.get("intent", "")),
            user_dims={str(k): str(v) for k, v in (body.get("user_dims") or {}).items()},
            mode=parse_governance_mode(body.get("mode")),
        )

    def get_run_registration(self, run_id: str) -> RunRegistration | None:
        try:
            return self.resolve_run(run_id)
        except RunNotRegisteredError:
            return None

    def governance_config_for(self, agent: str) -> dict:
        return self._request("GET", f"/v1/governance/{agent}").json()

    def create_run(self, rec: RunRecord) -> RunRecord:
        payload = {
            "run_id": rec.run_id,
            "agent": rec.agent,
            "status": rec.status,
            "parent_run": rec.parent_run,
            "parent_span": rec.parent_span,
            "halt_reason": rec.halt_reason,
            "detector": rec.detector,
            "cost_micros": rec.cost_micros,
            "steps": rec.steps,
            "started_at": rec.started_at,
            "ended_at": rec.ended_at,
            "task": rec.task,
            "dims": dict(rec.dims),
            "governance_events": list(rec.governance_events or []),
        }
        self._request("PUT", "/v1/run-records", json=payload)
        return rec

    def update_run(self, run_id: str, **fields: Any) -> None:
        self._request("PATCH", f"/v1/run-records/{run_id}", json=fields)

    def get_run(self, run_id: str) -> RunRecord | None:
        r = self._client.get(f"/v1/run-records/{run_id}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return _run(r.json())

    def list_runs(self, *, problematic_only: bool = False, limit: int = 200) -> list[RunRecord]:
        r = self._request(
            "GET",
            "/v1/run-records",
            params={"problematic_only": problematic_only, "limit": limit},
        )
        return [_run(x) for x in r.json()]

    def ledger_add_spent(self, budget_id: str, segment_key: str, period: str, delta: int) -> int:
        r = self._request(
            "POST",
            "/v1/ledger/spent/add",
            json={
                "budget_id": budget_id,
                "segment_key": segment_key,
                "period": period,
                "delta": delta,
            },
        )
        return int(r.json()["spent_micros"])

    def ledger_get_spent(self, budget_id: str, segment_key: str, period: str) -> int:
        r = self._request(
            "GET",
            "/v1/ledger/spent",
            params={"budget_id": budget_id, "segment_key": segment_key, "period": period},
        )
        return int(r.json()["spent_micros"])

    def ledger_admit(self, segment_key: str) -> int:
        r = self._request("POST", "/v1/ledger/inflight/admit", json={"segment_key": segment_key})
        return int(r.json()["count"])

    def ledger_complete(self, segment_key: str) -> int:
        r = self._request("POST", "/v1/ledger/inflight/complete", json={"segment_key": segment_key})
        return int(r.json()["count"])

    def ledger_inflight(self, segment_key: str) -> int:
        r = self._request("GET", "/v1/ledger/inflight", params={"segment_key": segment_key})
        return int(r.json()["count"])

    def ledger_mark_halted(self, run_id: str, reason: str = "") -> None:
        self._request("POST", "/v1/ledger/halt/mark", json={"run_id": run_id, "reason": reason})

    def ledger_is_halted(self, run_id: str) -> bool:
        r = self._request("GET", f"/v1/ledger/halt/{run_id}")
        return bool(r.json().get("halted"))

    def ledger_halt_reason(self, run_id: str) -> str | None:
        r = self._client.get(f"/v1/ledger/halt/{run_id}")
        r.raise_for_status()
        return r.json().get("halt_reason")

    def ledger_clear_halt(self, run_id: str) -> None:
        self._request("POST", "/v1/ledger/halt/clear", json={"run_id": run_id})

    # Trajectory index is plane-local for now; no-ops keep policies from crashing.
    def save_trajectory_snapshot(self, *args: Any, **kwargs: Any) -> None:
        return None

    def enqueue_trajectory_build(self, *args: Any, **kwargs: Any) -> None:
        return None

    def lookup_trajectory_index(self, **kwargs: Any) -> dict[str, Any] | None:
        return None

    def upsert_segment(self, seg: Segment) -> Segment:
        self._request("PUT", "/v1/segments", json=seg.__dict__)
        return seg

    def list_segments(self) -> list[Segment]:
        return [Segment(**x) for x in self._request("GET", "/v1/segments").json()]

    def upsert_budget(self, b: BudgetSpec) -> BudgetSpec:
        self._request("PUT", "/v1/budgets", json=b.__dict__)
        return b

    def list_budgets(self) -> list[BudgetSpec]:
        return [BudgetSpec(**x) for x in self._request("GET", "/v1/budgets").json()]

    def list_policy_instances(self) -> list[PolicyInstance]:
        return [PolicyInstance(**x) for x in self._request("GET", "/v1/policies").json()]


def _run(data: dict[str, Any]) -> RunRecord:
    return RunRecord(
        run_id=str(data["run_id"]),
        agent=str(data["agent"]),
        status=data.get("status", "running"),
        parent_run=data.get("parent_run"),
        parent_span=data.get("parent_span"),
        halt_reason=data.get("halt_reason"),
        detector=data.get("detector"),
        cost_micros=int(data.get("cost_micros", 0)),
        steps=int(data.get("steps", 0)),
        started_at=float(data.get("started_at", 0.0)),
        ended_at=data.get("ended_at"),
        task=data.get("task"),
        dims={str(k): str(v) for k, v in (data.get("dims") or {}).items()},
        governance_events=list(data.get("governance_events") or []),
    )
