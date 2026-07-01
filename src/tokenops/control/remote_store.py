"""HTTP client for the control-plane API — agents and UIs use this instead of SQLite."""

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
)
from tokenops.control.serde import (
    budget_from_dict,
    budget_to_dict,
    policy_from_dict,
    policy_to_dict,
    registration_from_dict,
    registration_to_dict,
    run_from_dict,
    run_to_dict,
    segment_from_dict,
    segment_to_dict,
)


class RemoteStore:
    """ControlStore backed by the standalone control-plane HTTP service."""

    def __init__(self, base_url: str, *, client: httpx.Client | None = None, timeout: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.Client(base_url=self._base_url, timeout=timeout)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        response = self._client.request(method, path, **kwargs)
        if response.status_code == 409:
            body = response.json()
            raise RunAlreadyRegisteredError(body.get("error", "run already registered"))
        if response.status_code == 404:
            body = response.json()
            msg = body.get("error", "not found")
            if "not registered" in msg.lower():
                raise RunNotRegisteredError(msg)
            return response
        response.raise_for_status()
        return response

    def upsert_segment(self, seg: Segment) -> Segment:
        r = self._request("PUT", "/v1/segments", json=segment_to_dict(seg))
        return segment_from_dict(r.json())

    def get_segment(self, sid: str) -> Segment | None:
        r = self._client.get(f"/v1/segments/{sid}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return segment_from_dict(r.json())

    def list_segments(self) -> list[Segment]:
        r = self._request("GET", "/v1/segments")
        return [segment_from_dict(x) for x in r.json()]

    def delete_segment(self, sid: str) -> None:
        self._request("DELETE", f"/v1/segments/{sid}")

    def upsert_budget(self, b: BudgetSpec) -> BudgetSpec:
        r = self._request("PUT", "/v1/budgets", json=budget_to_dict(b))
        return budget_from_dict(r.json())

    def get_budget(self, bid: str) -> BudgetSpec | None:
        r = self._client.get(f"/v1/budgets/{bid}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return budget_from_dict(r.json())

    def list_budgets(self) -> list[BudgetSpec]:
        r = self._request("GET", "/v1/budgets")
        return [budget_from_dict(x) for x in r.json()]

    def delete_budget(self, bid: str) -> None:
        self._request("DELETE", f"/v1/budgets/{bid}")

    def upsert_policy_instance(self, pi: PolicyInstance) -> PolicyInstance:
        r = self._request("PUT", "/v1/policies", json=policy_to_dict(pi))
        return policy_from_dict(r.json())

    def get_policy_instance(self, pid: str) -> PolicyInstance | None:
        r = self._client.get(f"/v1/policies/{pid}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return policy_from_dict(r.json())

    def list_policy_instances(self) -> list[PolicyInstance]:
        r = self._request("GET", "/v1/policies")
        return [policy_from_dict(x) for x in r.json()]

    def delete_policy_instance(self, pid: str) -> None:
        self._request("DELETE", f"/v1/policies/{pid}")

    def seed_default_governance_if_empty(self, governance: dict | None = None) -> bool:
        r = self._request("POST", "/v1/admin/seed-if-empty", json={"governance": governance})
        return bool(r.json().get("seeded"))

    def clear_all(self) -> None:
        self._request("POST", "/v1/admin/clear-all")

    def clear_governance(self) -> None:
        self._request("POST", "/v1/admin/clear-governance")

    def reseed_governance(self, governance: dict | None = None) -> bool:
        r = self._request("POST", "/v1/admin/reseed-governance", json={"governance": governance})
        return bool(r.json().get("seeded"))

    def register_run(self, reg: RunRegistration) -> RunRegistration:
        r = self._request("POST", "/v1/runs", json=registration_to_dict(reg))
        return registration_from_dict(r.json())

    def resolve_run(self, run_id: str) -> RunRegistration:
        r = self._client.get(f"/v1/runs/{run_id}/registration")
        if r.status_code == 404:
            raise RunNotRegisteredError(f"run {run_id!r} is not registered")
        r.raise_for_status()
        return registration_from_dict(r.json())

    def get_run_registration(self, run_id: str) -> RunRegistration | None:
        r = self._client.get(f"/v1/runs/{run_id}/registration")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return registration_from_dict(r.json())

    def governance_config_for(self, agent: str) -> dict:
        r = self._request("GET", f"/v1/governance/{agent}")
        return r.json()

    def create_run(self, rec: RunRecord) -> RunRecord:
        r = self._request("PUT", "/v1/run-records", json=run_to_dict(rec))
        return run_from_dict(r.json())

    def update_run(self, run_id: str, **fields: Any) -> None:
        self._request("PATCH", f"/v1/run-records/{run_id}", json=fields)

    def get_run(self, run_id: str) -> RunRecord | None:
        r = self._client.get(f"/v1/run-records/{run_id}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return run_from_dict(r.json())

    def list_runs(self, *, problematic_only: bool = False, limit: int = 200) -> list[RunRecord]:
        r = self._request(
            "GET",
            "/v1/run-records",
            params={"problematic_only": problematic_only, "limit": limit},
        )
        return [run_from_dict(x) for x in r.json()]

    def run_tag_keys(self, *, limit: int = 500) -> list[str]:
        r = self._request("GET", "/v1/run-records/tag-keys", params={"limit": limit})
        return list(r.json())

    def ledger_add_spent(self, budget_id: str, segment_key: str, period: str, delta: int) -> int:
        r = self._request(
            "POST",
            "/v1/ledger/spent/add",
            json={"budget_id": budget_id, "segment_key": segment_key, "period": period, "delta": delta},
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
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json().get("halt_reason")

    def ledger_clear_halt(self, run_id: str) -> None:
        self._request("POST", "/v1/ledger/halt/clear", json={"run_id": run_id})
