"""Wrap browser-use LLM ``ainvoke`` with TokenOps governance."""

from __future__ import annotations

from functools import wraps
from typing import Any

from tokenops.control import build_attribution, consume_carry
from tokenops.control.boundary import emit_observation, observation_from_crossing
from tokenops.control.core import CallRequest

from benchmarking.browseruse.session import current_active_run

_RETRY_BASE_CAP = 512
_MAX_CALL_RETRIES = 3


def _tighten_cap(cap: int | None) -> int:
    return max(64, (cap or _RETRY_BASE_CAP) // 2)


def _msg_role(msg) -> str | None:
    if isinstance(msg, dict):
        return msg.get("role")
    return getattr(msg, "role", None)


def _msg_content(msg) -> str:
    if isinstance(msg, dict):
        return str(msg.get("content", ""))
    content = getattr(msg, "content", msg)
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                parts.append(str(part.get("text", part)))
            else:
                parts.append(str(getattr(part, "text", part)))
        return "".join(parts)
    return str(content)


def _compact_messages(messages):
    """Drop duplicate non-system messages (context_compaction MUTATE)."""
    seen: set[tuple[str | None, str]] = set()
    out = []
    for msg in messages:
        role = _msg_role(msg)
        content = _msg_content(msg)
        if role == "system":
            out.append(msg)
            continue
        if isinstance(content, str) and content.startswith("[TokenOps trajectory hint"):
            out.append(msg)
            continue
        key = (role, content)
        if key in seen:
            continue
        seen.add(key)
        out.append(msg)
    return out


def _browser_user_message(text: str):
    try:
        from browser_use.llm.messages import UserMessage
    except ImportError:
        return {"role": "user", "content": text}
    return UserMessage(content=text)


def _estimate_tokens(messages) -> int:
    total = sum(len(_msg_content(msg)) for msg in (messages or []))
    return max(1, total // 4)


def fill_llm_ids(active, agent) -> None:
    llm = getattr(agent, "llm", None)
    if llm is not None:
        active.main_llm_id = id(llm)


def _is_main_llm(active, llm) -> bool:
    return active.main_llm_id is not None and id(llm) == active.main_llm_id


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
        main_llm = _is_main_llm(active, llm)
        primary_turn = main_llm and active._main_llm_calls == 0
        carry_before = len(active.controls.carry)
        active.governor.pre_call(
            CallRequest(
                attr=attr,
                provider=provider,
                model=model,
                estimated_input_tokens=_estimate_tokens(messages),
                max_output_tokens=active.controls.call.max_output_tokens,
                primary_agent_turn=primary_turn,
            )
        )

        use_model = active.controls.call.model_override or model
        dispatch_messages = list(messages)
        if main_llm:
            if primary_turn:
                for msg in active.controls.carry[carry_before:]:
                    text = str(msg)
                    if "trajectory hint" in text.lower():
                        active.trajectory_hint_fired = True
                        active.trajectory_hint_chars = len(text)
                        low = text.lower()
                        if "exact match" in low:
                            active.trajectory_hint_match = "exact"
                        elif "simhash match" in low:
                            active.trajectory_hint_match = "simhash"
            active._main_llm_calls += 1
            if active.controls.carry:
                dispatch_messages = consume_carry(
                    active.controls,
                    dispatch_messages,
                    as_user=_browser_user_message,
                )
            if active.controls.call.compact:
                dispatch_messages = _compact_messages(dispatch_messages)

        seg = f"run:{attr.run_id}"
        active.governor.ledger.admit(seg)
        try:
            cap = active.controls.call.max_output_tokens
            penalties: dict[str, float] = {}
            attempt = 0
            while True:
                active.controls.retry = False
                call_kwargs = dict(kwargs)
                if cap is not None:
                    call_kwargs.setdefault("max_tokens", cap)
                call_kwargs.update(penalties)
                raw = await orig(dispatch_messages, *args, **call_kwargs)
                emit_observation(
                    observation_from_crossing(
                        boundary_id="browseruse.chat",
                        kind="llm",
                        service="browseruse",
                        input_state={"message_count": len(dispatch_messages)},
                        result=raw,
                        provider=provider,
                        model=use_model,
                    )
                )
                if active.controls.retry and attempt < _MAX_CALL_RETRIES and main_llm:
                    attempt += 1
                    cap = _tighten_cap(cap)
                    penalties = {"frequency_penalty": 1.0, "presence_penalty": 0.6}
                    continue
                return raw
        finally:
            active.governor.ledger.complete(seg)

    object.__setattr__(llm, "ainvoke", governed_ainvoke)
    llm._tokenops_governed = True  # type: ignore[attr-defined]
