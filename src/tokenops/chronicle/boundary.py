"""Boundary decorator: Chronicle record/replay + TokenOps govern ingest."""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, TypeVar

from chronicle.envelope.schema import ActionResult, InputState, ToolCall
from chronicle.session import SessionMode, get_session

from tokenops.control.context import current_span

F = TypeVar("F", bound=Callable[..., Any])


def boundary(
    boundary_id: str,
    *,
    kind: str = "custom",
    extract_input: Callable[..., InputState] | None = None,
    extract_result: Callable[[Any], Any] | None = None,
) -> Callable[[F], F]:
    """Annotate a decision boundary for Chronicle record/replay and TokenOps ingest.

    LIVE mode: execute function, record envelope, optionally ``governor.observe``
    REPLAY + STUB: return fixture without executing
    REPLAY + LIVE: execute function (cut-point), capture input/result for assertions
    """

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            session = get_session()

            if session.mode == SessionMode.LIVE:
                return _record_call(
                    session, fn, boundary_id, kind, args, kwargs,
                    extract_input, extract_result,
                )

            invocation_index = session._replay_cursor.get(boundary_id, 0) + 1
            if session.replay_plan.should_stub(boundary_id, invocation_index):
                return session.stub_result(boundary_id, kind)

            return _live_cutpoint_call(
                session, fn, boundary_id, kind, args, kwargs,
                extract_input, extract_result, invocation_index,
            )

        return wrapper  # type: ignore[return-value]

    return decorator


def _default_input_state(args: tuple, kwargs: dict) -> InputState:
    graph_state: dict[str, Any] = {}
    if args and isinstance(args[0], dict):
        graph_state = dict(args[0])
    elif kwargs:
        graph_state = dict(kwargs)
    else:
        graph_state = {"args": list(args), "kwargs": kwargs}

    messages = graph_state.get("messages", [])
    if not messages and "user_message" in graph_state:
        messages = [{"role": "user", "content": graph_state["user_message"]}]

    return InputState(
        messages=messages,
        system_prompt=graph_state.get("system_prompt"),
        graph_state=graph_state,
    )


def _service_name() -> str:
    span = current_span()
    return span.service if span else "unknown"


def _tokenops_observe(
    boundary_id: str,
    kind: str,
    input_state: InputState,
    result: Any,
) -> None:
    """TokenOps extension: project crossing → Observation when governance is bound."""
    from tokenops.control.boundary import emit_observation, observation_from_crossing
    from tokenops.control.context import current_governance, current_registration

    if current_governance() is None or current_registration() is None:
        return
    gov = current_governance()
    obs = observation_from_crossing(
        boundary_id=boundary_id,
        kind=kind,
        service=_service_name(),
        input_state=_input_state_to_dict(input_state),
        result=result,
        provider=gov.provider if gov else "",
        model=gov.model if gov else "",
    )
    emit_observation(obs)


def _input_state_to_dict(input_state: InputState) -> dict[str, object]:
    d: dict[str, object] = dict(input_state.graph_state)
    if input_state.messages:
        d["messages"] = input_state.messages
    if input_state.system_prompt:
        d["system_prompt"] = input_state.system_prompt
    return d


def _to_raw_dict(result: Any) -> dict[str, Any] | None:
    if isinstance(result, dict):
        return result
    to_dict = getattr(result, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    model_dump = getattr(result, "model_dump", None)
    if callable(model_dump):
        return model_dump()
    try:
        from dataclasses import asdict, is_dataclass

        if is_dataclass(result) and not isinstance(result, type):
            return asdict(result)
    except TypeError:
        pass
    return None


def _result_to_action_result(result: Any, kind: str) -> ActionResult:
    """Extended conversion for TokenOps agent result types (SearchResult, ModelResponse)."""
    if kind == "tool" and isinstance(result, dict):
        return ActionResult(completion=result.get("status", str(result)), raw_response=result)
    if kind == "llm" and isinstance(result, dict):
        tool_calls = [
            ToolCall(
                id=tc.get("id"),
                name=tc.get("name", ""),
                arguments=tc.get("arguments", {}),
            )
            for tc in result.get("tool_calls", [])
        ]
        return ActionResult(
            tool_calls=tool_calls,
            completion=result.get("completion"),
            finish_reason=result.get("finish_reason"),
        )
    if hasattr(result, "content"):
        return ActionResult(
            completion=str(getattr(result, "content", "")),
            raw_response={
                "input_tokens": getattr(result, "input_tokens", 0),
                "output_tokens": getattr(result, "output_tokens", 0),
            },
        )
    if hasattr(result, "snippet"):
        return ActionResult(
            completion=getattr(result, "snippet", str(result))[:200],
            raw_response=_to_raw_dict(result),
        )
    raw = _to_raw_dict(result)
    return ActionResult(completion=str(result), raw_response=raw)


def _record_call(session, fn, boundary_id, kind, args, kwargs, extract_input, extract_result):
    input_state = (
        extract_input(*args, **kwargs)
        if extract_input
        else _default_input_state(args, kwargs)
    )
    result = fn(*args, **kwargs)
    if extract_result:
        result = extract_result(result)
    action_result = _result_to_action_result(result, kind)
    session.record_envelope(boundary_id, kind, input_state, action_result)
    _tokenops_observe(boundary_id, kind, input_state, result)
    return result


def _live_cutpoint_call(
    session, fn, boundary_id, kind, args, kwargs,
    extract_input, extract_result, invocation_index,
):
    input_state = (
        extract_input(*args, **kwargs)
        if extract_input
        else _default_input_state(args, kwargs)
    )
    session.capture_live_input(boundary_id, invocation_index, input_state)
    result = fn(*args, **kwargs)
    if extract_result:
        result = extract_result(result)
    session.capture_live_result(boundary_id, invocation_index, result)
    session.next_invocation(boundary_id)
    session._replay_cursor[boundary_id] = invocation_index
    _tokenops_observe(boundary_id, kind, input_state, result)
    return result
