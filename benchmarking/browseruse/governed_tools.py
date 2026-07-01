"""Bridge browser-use ``Tools.act`` into TokenOps observations."""

from __future__ import annotations

from functools import wraps

from tokenops.control.boundary import emit_observation, observation_from_crossing
from tokenops.control.context import current_governance, current_registration

from benchmarking.browseruse.session import current_active_run


class _ToolSnippet:
    def __init__(self, text: str) -> None:
        self.snippet = text
        self.completeness = None


def _action_label(action) -> str:
    if hasattr(action, "model_dump"):
        for key, val in action.model_dump(exclude_unset=True).items():
            if val is not None:
                return str(key)
    for attr in ("action", "name", "action_name"):
        val = getattr(action, attr, None)
        if val:
            return str(val)
    return type(action).__name__


def _action_args(action) -> dict:
    if hasattr(action, "model_dump"):
        data = action.model_dump(exclude_unset=True)
        for key, val in data.items():
            if val is not None:
                if hasattr(val, "model_dump"):
                    return {key: val.model_dump(exclude_unset=True)}
                return {key: val}
    return {}


def _result_observation(result) -> str:
    if hasattr(result, "extracted_content") and result.extracted_content:
        return str(result.extracted_content)
    if hasattr(result, "error") and result.error:
        return str(result.error)
    if hasattr(result, "long_term_memory") and result.long_term_memory:
        return str(result.long_term_memory)
    return str(result)


def _substitute_result(result, override: str):
    if hasattr(result, "model_copy"):
        updates: dict = {"extracted_content": override}
        if getattr(result, "error", None):
            updates["error"] = None
        if hasattr(result, "long_term_memory"):
            updates["long_term_memory"] = override[:500]
        return result.model_copy(update=updates)
    return override


def make_governed_act(orig_act):
    @wraps(orig_act)
    async def governed_act(self, action, browser_session, *args, **kwargs):
        if current_active_run() is None or current_governance() is None:
            return await orig_act(self, action, browser_session, *args, **kwargs)

        result = await orig_act(self, action, browser_session, *args, **kwargs)
        if current_registration() is not None:
            active = current_active_run()
            label = _action_label(action)
            args_summary = _action_args(action)
            obs_text = _result_observation(result)
            emit_observation(
                observation_from_crossing(
                    boundary_id=f"browseruse.tool.{label}",
                    kind="tool",
                    service="browseruse",
                    input_state={"name": label, "args": args_summary},
                    result=_ToolSnippet(obs_text),
                )
            )
            if active is not None:
                override = active.controls.take_tool_result()
                if override:
                    result = _substitute_result(result, override)
        return result

    return governed_act
