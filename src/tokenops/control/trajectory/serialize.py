"""Serialize BoundaryStep windows for durable snapshot storage."""

from __future__ import annotations

import json
from typing import Any, Sequence

from tokenops.control.core import BoundaryStep, Usage


def _usage_to_dict(u: Usage | None) -> dict[str, int] | None:
    if u is None:
        return None
    return {"input": u.input, "output": u.output, "cached": u.cached, "reasoning": u.reasoning}


def _usage_from_dict(d: dict[str, int] | None) -> Usage | None:
    if not d:
        return None
    return Usage(
        input=d.get("input", 0),
        output=d.get("output", 0),
        cached=d.get("cached", 0),
        reasoning=d.get("reasoning", 0),
    )


def step_to_dict(step: BoundaryStep) -> dict[str, Any]:
    return {
        "step": step.step,
        "ts": step.ts,
        "node_type": step.node_type,
        "boundary_id": step.boundary_id,
        "cum_spent_micros": step.cum_spent_micros,
        "input": dict(step.input),
        "output": dict(step.output),
        "tags": dict(step.tags),
        "usage": _usage_to_dict(step.usage),
        "signature": step.signature,
        "result_hash": step.result_hash,
    }


def step_from_dict(d: dict[str, Any]) -> BoundaryStep:
    return BoundaryStep(
        step=d["step"],
        ts=d["ts"],
        node_type=d["node_type"],
        boundary_id=d["boundary_id"],
        cum_spent_micros=d["cum_spent_micros"],
        input=d.get("input") or {},
        output=d.get("output") or {},
        tags=d.get("tags") or {},
        usage=_usage_from_dict(d.get("usage")),
        signature=d.get("signature"),
        result_hash=d.get("result_hash"),
    )


def window_to_json(steps: Sequence[BoundaryStep]) -> str:
    return json.dumps([step_to_dict(s) for s in steps], separators=(",", ":"))


def window_from_json(raw: str) -> list[BoundaryStep]:
    data = json.loads(raw)
    return [step_from_dict(d) for d in data]
