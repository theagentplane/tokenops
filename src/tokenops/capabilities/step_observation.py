"""The brownfield IN tap: map an agent's own step objects to observations.

``make_on_step`` returns a callback you pass straight into an existing agent's ``on_step=...``
hook. It maps the agent's step to an ``Observation`` and feeds the Governor. If a policy HALTs,
``Halt`` propagates out of the agent's loop, which is the brownfield control channel with no
change to agent logic.

The adapter **duck-types** the step object (reads ``.action`` / ``.query`` / ``.tokens``), so
TokenOps never imports agent code: the dependency stays one-way.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from typing import Any

from tokenops.framework.core import Attribution, Observation
from tokenops.framework.engine import Governor
from tokenops.framework.observation_utils import short_hash, span_fields, tool_signature
from tokenops.framework.usage import usage_from_counts

__all__ = ["make_on_step", "step_to_observation"]


def step_to_observation(
    step: Any,
    attr: Attribution,
    *,
    ts: float,
    provider: str = "",
    model: str = "",
    service: str = "",
) -> Observation:
    """Map an agent step object to an ``Observation`` with ``boundary_tags``."""
    action = getattr(step, "action", "")
    span = span_fields(service)
    if action == "model":
        tu = getattr(step, "tokens", None)
        usage = usage_from_counts(tu)
        boundary_tags = {
            "node_type": "llm",
            "provider": provider,
            "model": model,
        }
        return Observation(
            attr=attr,
            node_type="llm",
            boundary_id=f"{getattr(step, 'agent', span['service'] or 'agent')}.chat",
            ts=ts,
            usage=usage,
            provider=provider,
            model=model,
            output={"text": getattr(step, "detail", "")},
            boundary_tags=boundary_tags,
            **span,
        )
    if action == "delegate":
        boundary_tags = {"node_type": "delegate", "target": getattr(step, "detail", "")}
        return Observation(
            attr=attr,
            node_type="delegate",
            boundary_id="delegate",
            ts=ts,
            input={"target_agent": getattr(step, "detail", "")},
            boundary_tags=boundary_tags,
            **span,
        )
    query = getattr(step, "query", "")
    args = {"query": query}
    tool_name = action or "tool"
    boundary_tags = {"node_type": "tool", "tool": tool_name}
    return Observation(
        attr=attr,
        node_type="tool",
        boundary_id=tool_name,
        ts=ts,
        input={"name": tool_name, "args": args},
        output={
            "completeness": getattr(step, "completeness", None),
            "snippet": getattr(step, "detail", ""),
        },
        signature=tool_signature(tool_name, args),
        result_hash=short_hash(getattr(step, "detail", "")),
        boundary_tags=boundary_tags,
        **span,
    )


def make_on_step(
    governor: Governor, attr: Attribution, *, provider: str, model: str, service: str = ""
) -> Callable[[Any], None]:
    """Return a callback for an agent's ``on_step``."""
    counter = itertools.count(1)

    def on_step(ev: Any) -> None:
        obs = step_to_observation(
            ev,
            attr,
            ts=float(next(counter)),
            provider=provider,
            model=model,
            service=service,
        )
        governor.observe(obs)

    return on_step
