"""Standalone control-plane HTTP API — sole owner of ``tokenops.db`` when split."""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from tokenops.chronicle.session import reset_session
from tokenops.control.models import RunAlreadyRegisteredError, RunNotRegisteredError
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
from tokenops.control.store import SqliteStore, new_id


def create_control_plane_app(store: SqliteStore | None = None) -> FastAPI:
    db_path = os.environ.get("TOKENOPS_DB", "tokenops.db")
    backend = store or SqliteStore(db_path)
    app = FastAPI(title="tokenops-control-plane")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "control-plane"}

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        if store is None:
            backend.close()

    # ---- registration ----------------------------------------------------- #

    @app.post("/v1/runs")
    async def register_run(request: Request) -> JSONResponse:
        payload = await request.json()
        run_id = str(payload.get("run_id") or "").strip() or new_id("run")
        reg = registration_from_dict(
            {"run_id": run_id, "intent": payload.get("intent", ""), "user_dims": payload.get("user_dims") or {}}
        )
        try:
            saved = backend.register_run(reg)
        except RunAlreadyRegisteredError as exc:
            return JSONResponse({"error": str(exc)}, status_code=409)
        reset_session().begin_trace(saved.run_id)
        return JSONResponse(registration_to_dict(saved), status_code=201)

    @app.get("/v1/runs/{run_id}/registration")
    async def get_registration(run_id: str) -> JSONResponse:
        reg = backend.get_run_registration(run_id)
        if reg is None:
            return JSONResponse({"error": f"run {run_id!r} is not registered"}, status_code=404)
        return JSONResponse(registration_to_dict(reg))

    # ---- governance ------------------------------------------------------- #

    @app.get("/v1/governance/{agent}")
    async def governance_for_agent(agent: str) -> dict[str, Any]:
        return backend.governance_config_for(agent)

    @app.get("/v1/segments")
    async def list_segments() -> list[dict[str, Any]]:
        return [segment_to_dict(s) for s in backend.list_segments()]

    @app.put("/v1/segments")
    async def upsert_segment(request: Request) -> dict[str, Any]:
        seg = segment_from_dict(await request.json())
        return segment_to_dict(backend.upsert_segment(seg))

    @app.get("/v1/segments/{sid}")
    async def get_segment(sid: str) -> JSONResponse:
        seg = backend.get_segment(sid)
        if seg is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(segment_to_dict(seg))

    @app.delete("/v1/segments/{sid}")
    async def delete_segment(sid: str) -> dict[str, str]:
        backend.delete_segment(sid)
        return {"status": "deleted"}

    @app.get("/v1/budgets")
    async def list_budgets() -> list[dict[str, Any]]:
        return [budget_to_dict(b) for b in backend.list_budgets()]

    @app.put("/v1/budgets")
    async def upsert_budget(request: Request) -> dict[str, Any]:
        spec = budget_from_dict(await request.json())
        return budget_to_dict(backend.upsert_budget(spec))

    @app.get("/v1/budgets/{bid}")
    async def get_budget(bid: str) -> JSONResponse:
        spec = backend.get_budget(bid)
        if spec is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(budget_to_dict(spec))

    @app.delete("/v1/budgets/{bid}")
    async def delete_budget(bid: str) -> dict[str, str]:
        backend.delete_budget(bid)
        return {"status": "deleted"}

    @app.get("/v1/policies")
    async def list_policies() -> list[dict[str, Any]]:
        return [policy_to_dict(p) for p in backend.list_policy_instances()]

    @app.put("/v1/policies")
    async def upsert_policy(request: Request) -> dict[str, Any]:
        pi = policy_from_dict(await request.json())
        try:
            saved = backend.upsert_policy_instance(pi)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return policy_to_dict(saved)

    @app.get("/v1/policies/{pid}")
    async def get_policy(pid: str) -> JSONResponse:
        pi = backend.get_policy_instance(pid)
        if pi is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(policy_to_dict(pi))

    @app.delete("/v1/policies/{pid}")
    async def delete_policy(pid: str) -> dict[str, str]:
        backend.delete_policy_instance(pid)
        return {"status": "deleted"}

    # ---- run history ------------------------------------------------------ #

    @app.put("/v1/run-records")
    async def create_run_record(request: Request) -> dict[str, Any]:
        rec = run_from_dict(await request.json())
        return run_to_dict(backend.create_run(rec))

    @app.patch("/v1/run-records/{run_id}")
    async def update_run_record(run_id: str, request: Request) -> dict[str, str]:
        fields = await request.json()
        backend.update_run(run_id, **fields)
        return {"status": "updated"}

    @app.get("/v1/run-records/{run_id}")
    async def get_run_record(run_id: str) -> JSONResponse:
        rec = backend.get_run(run_id)
        if rec is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(run_to_dict(rec))

    @app.get("/v1/run-records")
    async def list_run_records(problematic_only: bool = False, limit: int = 200) -> list[dict[str, Any]]:
        return [run_to_dict(r) for r in backend.list_runs(problematic_only=problematic_only, limit=limit)]

    @app.get("/v1/run-records/tag-keys")
    async def run_tag_keys(limit: int = 500) -> list[str]:
        return backend.run_tag_keys(limit=limit)

    # ---- ledger ----------------------------------------------------------- #

    @app.post("/v1/ledger/spent/add")
    async def ledger_add_spent(request: Request) -> dict[str, int]:
        body = await request.json()
        spent = backend.ledger_add_spent(
            body["budget_id"], body["segment_key"], body.get("period", "lifetime"), int(body["delta"]),
        )
        return {"spent_micros": spent}

    @app.get("/v1/ledger/spent")
    async def ledger_get_spent(budget_id: str, segment_key: str, period: str = "lifetime") -> dict[str, int]:
        return {"spent_micros": backend.ledger_get_spent(budget_id, segment_key, period)}

    @app.post("/v1/ledger/inflight/admit")
    async def ledger_admit(request: Request) -> dict[str, int]:
        body = await request.json()
        return {"count": backend.ledger_admit(body["segment_key"])}

    @app.post("/v1/ledger/inflight/complete")
    async def ledger_complete(request: Request) -> dict[str, int]:
        body = await request.json()
        return {"count": backend.ledger_complete(body["segment_key"])}

    @app.get("/v1/ledger/inflight")
    async def ledger_inflight(segment_key: str) -> dict[str, int]:
        return {"count": backend.ledger_inflight(segment_key)}

    @app.post("/v1/ledger/halt/mark")
    async def ledger_mark_halted(request: Request) -> dict[str, str]:
        body = await request.json()
        backend.ledger_mark_halted(body["run_id"], body.get("reason", ""))
        return {"status": "halted"}

    @app.get("/v1/ledger/halt/{run_id}")
    async def ledger_halt_status(run_id: str) -> dict[str, Any]:
        return {
            "halted": backend.ledger_is_halted(run_id),
            "halt_reason": backend.ledger_halt_reason(run_id),
        }

    @app.post("/v1/ledger/halt/clear")
    async def ledger_clear_halt(request: Request) -> dict[str, str]:
        body = await request.json()
        backend.ledger_clear_halt(body["run_id"])
        return {"status": "cleared"}

    # ---- admin ------------------------------------------------------------ #

    @app.post("/v1/admin/seed-if-empty")
    async def seed_if_empty(request: Request) -> dict[str, bool]:
        body = await request.json()
        seeded = backend.seed_default_governance_if_empty(body.get("governance"))
        return {"seeded": seeded}

    @app.post("/v1/admin/clear-all")
    async def clear_all() -> dict[str, str]:
        backend.clear_all()
        return {"status": "cleared"}

    @app.post("/v1/admin/clear-governance")
    async def clear_governance() -> dict[str, str]:
        backend.clear_governance()
        return {"status": "cleared"}

    @app.post("/v1/admin/reseed-governance")
    async def reseed_governance(request: Request) -> dict[str, bool]:
        body = await request.json()
        seeded = backend.reseed_governance(body.get("governance"))
        return {"seeded": seeded}

    return app
