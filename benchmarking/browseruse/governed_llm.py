"""Wrap browser-use LLM ``ainvoke`` with TokenOps governance."""

from __future__ import annotations

from functools import wraps
from typing import Any

from tokenops.control import build_attribution
from tokenops.control.boundary import emit_observation, observation_from_crossing
from tokenops.control.core import CallRequest

from benchmarking.browseruse.session import current_active_run


def _estimate_tokens(messages) -> int:
    total = 0
    for msg in messages or []:
        if isinstance(msg, dict):
            total += len(str(msg.get("content", "")))
        else:
            total += len(str(getattr(msg, "content", msg)))
    return max(1, total // 4)


def fill_llm_ids(active, agent) -> None:
    pass


def wrap_ainvoke(llm: Any) -> None:
    if getattr(llm, "_tokenops_governed", False):
        return
    orig = llm.ainvoke
    provider = getattr(llm, "provider", "openai")
    model = getattr(llm, "model", "gpt-4o-mini")

    @wraps(orig)
    async def governed_ainvoke(messages, *args, **kwargs):
        active = current_active_run()
        if active is None:
            return await orig(messages, *args, **kwargs)

        attr = build_attribution(active.registration, service="browseruse")
        active.controls.begin_call()
        active.governor.pre_call(
            CallRequest(
                attr=attr,
                provider=provider,
                model=model,
                estimated_input_tokens=_estimate_tokens(messages),
                max_output_tokens=active.controls.call.max_output_tokens,
            )
        )
        seg = f"run:{attr.run_id}"
        active.governor.ledger.admit(seg)
        try:
            raw = await orig(messages, *args, **kwargs)
            emit_observation(
                observation_from_crossing(
                    boundary_id="browseruse.chat",
                    kind="llm",
                    service="browseruse",
                    input_state={"message_count": len(messages)},
                    result=raw,
                    provider=provider,
                    model=model,
                )
            )
            return raw
        finally:
            active.governor.ledger.complete(seg)

    object.__setattr__(llm, "ainvoke", governed_ainvoke)
    llm._tokenops_governed = True  # type: ignore[attr-defined]
