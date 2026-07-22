"""Async LLM bridge — governs MetaGPT ``BaseLLM.acompletion_text``."""

from __future__ import annotations

import time
from typing import Any

from tokenops.control.boundary import emit_observation, observation_from_crossing
from tokenops.control.context import current_governance
from tokenops.control.core import CallRequest, Usage
from tokenops.control.integration import consume_carry
from tokenops.providers.types import ModelResponse

from benchmarking.metagpt.crossing import resolve_llm_crossing
from benchmarking.metagpt.session import current_active_run, record_policy_signal


def _estimate_input_tokens(messages) -> int:
    return max(1, len(str(messages)) // 4)


def _usage_from_result(result, text: str) -> Usage:
    usage = getattr(result, "usage", None)
    if usage is None and isinstance(result, dict):
        usage = result.get("usage")
    if usage is None:
        return Usage(input=_estimate_input_tokens([]), output=max(1, len(text) // 4))
    if hasattr(usage, "model_dump"):
        usage = usage.model_dump()
    elif not isinstance(usage, dict):
        usage = {
            "prompt_tokens": getattr(usage, "prompt_tokens", 0),
            "completion_tokens": getattr(usage, "completion_tokens", 0),
        }
    prompt = int(usage.get("prompt_tokens", 0) or 0)
    completion = int(usage.get("completion_tokens", 0) or 0)
    return Usage(input=prompt, output=completion)


def _provider_model(llm) -> tuple[str, str]:
    config = getattr(llm, "config", None)
    api_type = getattr(config, "api_type", None)
    provider = str(api_type.value if hasattr(api_type, "value") else api_type or "openai")
    model = getattr(llm, "model", None) or getattr(config, "model", "gpt-4o-mini")
    return provider, str(model)


def _text_from_result(result, llm) -> str:
    if isinstance(result, str):
        return str(result)
    get_text = getattr(llm, "get_choice_text", None)
    if callable(get_text):
        try:
            return str(get_text(result))
        except Exception:  # noqa: BLE001
            pass
    return str(result)


def _record_carry_signals(carry: list[str]) -> None:
    for text in carry:
        lower = text.lower()
        if "progress_guard" in lower or "no progress" in lower:
            record_policy_signal("progress_guard")
        if "budget pressure" in lower:
            record_policy_signal("cost_guard")


def wrap_llm(llm: Any) -> Any:
    if getattr(llm, "_tokenops_governed", False):
        return llm

    inner = getattr(llm, "acompletion_text", None)
    if inner is None or not callable(inner):
        return llm

    async def governed_acompletion_text(messages, stream: bool = False, timeout=None, **kwargs):
        active = current_active_run()
        if active is None:
            return await inner(messages, stream=stream, timeout=timeout, **kwargs)

        gov_ctx = current_governance()
        if gov_ctx is None:
            return await inner(messages, stream=stream, timeout=timeout, **kwargs)

        governor = active.governor
        controls = active.controls
        attr = gov_ctx.attr
        provider, model = _provider_model(llm)
        boundary_id, input_state, extra_tags = resolve_llm_crossing(llm, active, messages)

        controls.begin_call()
        governor.pre_call(
            CallRequest(
                attr=attr,
                provider=provider,
                model=model,
                estimated_input_tokens=_estimate_input_tokens(messages),
                max_output_tokens=controls.call.max_output_tokens,
            )
        )

        use_model = controls.call.model_override or model
        if use_model != model and hasattr(llm, "with_model"):
            llm.with_model(use_model)
            record_policy_signal("cost_guard_downgrade")
        elif controls.call.model_override:
            record_policy_signal("cost_guard_downgrade")

        if controls.carry:
            _record_carry_signals(list(controls.carry))
        payload = consume_carry(controls, messages)

        seg = f"run:{attr.run_id}"
        governor.ledger.admit(seg)
        try:
            result = await inner(payload, stream=stream, timeout=timeout, **kwargs)
        finally:
            governor.ledger.complete(seg)

        text = _text_from_result(result, llm)
        usage = _usage_from_result(result, text)
        resp = ModelResponse(content=text, input_tokens=usage.input, output_tokens=usage.output)
        emit_observation(
            observation_from_crossing(
                boundary_id=boundary_id,
                kind="llm",
                service="metagpt",
                input_state=input_state,
                result=resp,
                provider=provider,
                model=use_model,
                ts=time.time(),
                extra_tags=extra_tags,
            )
        )
        active.models_used.add(use_model)
        return result

    object.__setattr__(llm, "acompletion_text", governed_acompletion_text)
    object.__setattr__(llm, "_tokenops_governed", True)
    return llm


def fill_llm_ids(active, role) -> None:
    active.think_llm_id = id(role.llm)
    todo = getattr(role.rc, "todo", None)
    if todo is not None and getattr(todo, "llm", None) is not None:
        active.action_llm_id = id(todo.llm)
    elif role.actions:
        active.action_llm_id = id(role.actions[0].llm)


def wrap_role_llms(role) -> None:
    wrap_llm(role.llm)
    for action in getattr(role, "actions", []) or []:
        if getattr(action, "llm", None) is not None:
            wrap_llm(action.llm)
