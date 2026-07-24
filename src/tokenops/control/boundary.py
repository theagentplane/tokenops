"""TokenOps govern projection helpers for boundary crossings.

Chronicle record/replay lives in the ``chronicle`` package; this module maps
crossings to :class:`Observation` for the control-plane ledger.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping
from typing import Any

from tokenops.control.attribution import _build_attribution, require_registration
from tokenops.control.context import current_governance, current_span
from tokenops.control.core import NodeType, Observation, Usage

_KIND_MAP: dict[str, NodeType] = {
    "llm": "llm",
    "tool": "tool",
    "delegate": "delegate",
    "custom": "tool",
}


def _tool_signature(name: str, args) -> str:
    payload = json.dumps([name, args], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _hash(text: object) -> str:
    return hashlib.sha256(str(text).encode()).hexdigest()[:16]


def _span_fields(service: str) -> dict:
    span = current_span()
    if span is None:
        return {"service": service, "span_id": "", "parent_span_id": None}
    return {
        "service": span.service or service,
        "span_id": span.span_id,
        "parent_span_id": span.parent_span_id,
    }


def observation_from_crossing(
    *,
    boundary_id: str,
    kind: str,
    service: str,
    input_state: Mapping[str, object],
    result: Any,
    provider: str = "",
    model: str = "",
    ts: float | None = None,
    extra_tags: Mapping[str, str] | None = None,
) -> Observation:
    reg = require_registration()
    attr = _build_attribution(reg, service=service)
    node_type = _KIND_MAP.get(kind, "tool")
    tags = {"node_type": node_type, **(extra_tags or {})}
    if provider:
        tags["provider"] = provider
    if model:
        tags["model"] = model

    usage: Usage | None = None
    output: Mapping[str, object] = {}
    signature: str | None = None
    result_hash: str | None = None
    rolled_up: int = 0

    if node_type == "llm":
        usage_obj = getattr(result, "usage", None)
        if usage_obj is not None:
            usage = Usage(
                input=int(
                    getattr(usage_obj, "prompt_tokens", 0)
                    or getattr(usage_obj, "input_tokens", 0)
                    or 0
                ),
                output=int(
                    getattr(usage_obj, "completion_tokens", 0)
                    or getattr(usage_obj, "output_tokens", 0)
                    or 0
                ),
            )
        else:
            usage = Usage(
                input=int(getattr(result, "input_tokens", 0) or 0),
                output=int(getattr(result, "output_tokens", 0) or 0),
            )
        text = getattr(result, "content", None)
        if text is None and hasattr(result, "completion"):
            text = getattr(result, "completion", result)
        output = {"text": str(text)[:500]}
    elif node_type == "tool":
        name = str(input_state.get("name", boundary_id))
        args = input_state.get("args", input_state)
        signature = _tool_signature(name, args)
        if hasattr(result, "snippet"):
            full = str(getattr(result, "snippet", ""))
            output = {
                "snippet": full[:500],
                "completeness": getattr(result, "completeness", None),
                "size_chars": len(full),  # true size (pre-truncation) so tool_output_cap can detect
            }
            result_hash = _hash(full)
        else:
            full = str(result)
            output = {"result": full[:500], "size_chars": len(full)}
            result_hash = _hash(result)
        tags.setdefault("tool", name)
    elif node_type == "delegate":
        raw_roll = getattr(result, "rolled_up_cost_micros", None)
        if raw_roll is None:
            raw_roll = input_state.get("rolled_up_cost_micros", 0)
        rolled_up = int(raw_roll) if isinstance(raw_roll, (int, float, str)) else 0
        output = dict(result) if isinstance(result, dict) else {"result": str(result)}

    return Observation(
        attr=attr,
        node_type=node_type,
        boundary_id=boundary_id,
        ts=ts if ts is not None else time.time(),
        input=dict(input_state),
        output=output,
        provider=provider,
        model=model,
        usage=usage,
        signature=signature,
        result_hash=result_hash,
        rolled_up_cost_micros=rolled_up,
        boundary_tags=tags,
        **_span_fields(service),
    )


def emit_observation(obs: Observation) -> None:
    gov = current_governance()
    if gov is None:
        return
    gov.governor.observe(obs)
