"""JSON helpers for control-plane HTTP payloads."""

from __future__ import annotations

from typing import Any

from tokenops.control.models import (
    BudgetSpec,
    PolicyInstance,
    RunRecord,
    RunRegistration,
    Segment,
)


def registration_to_dict(reg: RunRegistration) -> dict[str, Any]:
    return {"run_id": reg.run_id, "intent": reg.intent, "user_dims": dict(reg.user_dims)}


def registration_from_dict(data: dict[str, Any]) -> RunRegistration:
    return RunRegistration(
        run_id=str(data["run_id"]),
        intent=str(data.get("intent", "")),
        user_dims={str(k): str(v) for k, v in (data.get("user_dims") or {}).items()},
    )


def segment_to_dict(seg: Segment) -> dict[str, Any]:
    return {
        "id": seg.id,
        "name": seg.name,
        "dimension": seg.dimension,
        "tag_key": seg.tag_key,
        "match_value": seg.match_value,
    }


def segment_from_dict(data: dict[str, Any]) -> Segment:
    return Segment(
        id=str(data["id"]),
        name=str(data["name"]),
        dimension=data.get("dimension", "run"),
        tag_key=data.get("tag_key"),
        match_value=data.get("match_value"),
    )


def budget_to_dict(b: BudgetSpec) -> dict[str, Any]:
    return {
        "id": b.id,
        "limit_micros": b.limit_micros,
        "dimension": b.dimension,
        "tag_key": b.tag_key,
        "period": b.period,
    }


def budget_from_dict(data: dict[str, Any]) -> BudgetSpec:
    return BudgetSpec(
        id=str(data["id"]),
        limit_micros=data.get("limit_micros"),
        dimension=data.get("dimension", "run"),
        tag_key=data.get("tag_key"),
        period=data.get("period", "lifetime"),
    )


def policy_to_dict(pi: PolicyInstance) -> dict[str, Any]:
    return {
        "id": pi.id,
        "template": pi.template,
        "params": dict(pi.params),
        "agent": pi.agent,
        "budget_id": pi.budget_id,
        "segment_id": pi.segment_id,
        "enabled": pi.enabled,
    }


def policy_from_dict(data: dict[str, Any]) -> PolicyInstance:
    return PolicyInstance(
        id=str(data["id"]),
        template=str(data["template"]),
        params=dict(data.get("params") or {}),
        agent=data.get("agent"),
        budget_id=data.get("budget_id"),
        segment_id=data.get("segment_id"),
        enabled=bool(data.get("enabled", True)),
    )


def run_to_dict(rec: RunRecord) -> dict[str, Any]:
    return {
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
    }


def run_from_dict(data: dict[str, Any]) -> RunRecord:
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
    )
