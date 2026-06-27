"""Integration — the brownfield IN tap that drops into a vanilla agent.

``make_on_step`` returns a callback you pass straight into an existing agent's
``on_step=...`` hook. It maps the agent's own step object to a contract ``Observation`` and
feeds the Governor. If a policy HALTs, ``Halt`` propagates out of the agent's loop — which
is exactly the brownfield control channel, with no change to agent logic.

The adapter **duck-types** the step object (reads ``.action`` / ``.query`` / ``.tokens``),
so ``tokenops.control`` never imports ``tokenops.agents`` — the dependency stays one-way.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from typing import Callable

from tokenops.control.context import current_span
from tokenops.control.boundary import emit_observation, observation_from_crossing
from tokenops.control.context import current_governance, current_registration
from tokenops.control.core import Attribution, CallRequest, Observation, Usage


def tool_signature(name: str, args) -> str:
    payload = json.dumps([name, args], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _hash(text: object) -> str:
    return hashlib.sha256(str(text).encode()).hexdigest()[:16]


def _span_fields(*, service: str = "") -> dict:
    span = current_span()
    if span is None:
        return {"service": service, "span_id": "", "parent_span_id": None}
    return {
        "service": span.service or service,
        "span_id": span.span_id,
        "parent_span_id": span.parent_span_id,
    }


def step_to_observation(
    step,
    attr: Attribution,
    *,
    ts: float,
    provider: str = "",
    model: str = "",
    service: str = "",
) -> Observation:
    """Map an agent step object to an ``Observation`` with ``boundary_tags``."""
    action = getattr(step, "action", "")
    span = _span_fields(service=service)
    if action == "model":
        tu = getattr(step, "tokens", None)
        usage = Usage(
            input=getattr(tu, "input_tokens", 0) if tu else 0,
            output=getattr(tu, "output_tokens", 0) if tu else 0,
        )
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
        result_hash=_hash(getattr(step, "detail", "")),
        boundary_tags=boundary_tags,
        **span,
    )


def make_on_step(governor, attr: Attribution, *, provider: str, model: str, service: str = ""):
    """Return a callback for an agent's ``on_step``."""
    counter = itertools.count(1)

    def on_step(ev) -> None:
        obs = step_to_observation(
            ev, attr, ts=float(next(counter)), provider=provider, model=model, service=service,
        )
        governor.observe(obs)

    return on_step


#: A dispatch callable: (provider, model, messages, max_output_tokens) -> response.
DispatchFn = Callable[..., object]


def _estimate_input_tokens(messages) -> int:
    return max(1, len(str(messages)) // 4)


def wrap_complete(
    governor,
    controls,
    attr: Attribution,
    *,
    provider: str,
    model: str,
    dispatch: DispatchFn,
    est_input_fn: Callable[[object], int] | None = None,
    service: str = "",
):
    """Wrap a ``complete(provider, model, messages)`` entry point for **pre_call** governance."""
    estimate = est_input_fn or _estimate_input_tokens
    seg = f"run:{attr.run_id}"

    def governed(p: str, m: str, messages) -> object:
        controls.begin_call()
        request = CallRequest(
            attr=attr, provider=provider, model=m,
            estimated_input_tokens=estimate(messages),
            max_output_tokens=controls.call.max_output_tokens,
        )
        governor.pre_call(request)

        use_model = controls.call.model_override or m
        if controls.carry:
            messages = [{"role": "system", "content": c} for c in controls.carry] + list(messages)
            controls.carry.clear()

        governor.ledger.admit(seg)
        try:
            response = dispatch(p, use_model, messages, max_output_tokens=controls.call.max_output_tokens)
            if current_governance() is not None and current_registration() is not None:
                emit_observation(
                    observation_from_crossing(
                        boundary_id=f"{service or attr.agent}.chat",
                        kind="llm",
                        service=service or attr.agent,
                        input_state={"message_count": len(messages)},
                        result=response,
                        provider=provider,
                        model=use_model,
                    )
                )
            return response
        finally:
            governor.ledger.complete(seg)

    return governed


def observation_from_delegate(
    attr: Attribution,
    *,
    boundary_id: str,
    rolled_up_cost_micros: int,
    ts: float,
    service: str = "",
) -> Observation:
    """Build a delegate rollup observation after an A2A child returns."""
    span = _span_fields(service=service)
    return Observation(
        attr=attr,
        node_type="delegate",
        boundary_id=boundary_id,
        ts=ts,
        rolled_up_cost_micros=rolled_up_cost_micros,
        boundary_tags={"node_type": "delegate"},
        **span,
    )
