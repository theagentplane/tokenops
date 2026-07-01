"""Action bridge — governs ``Action.run``."""

from __future__ import annotations

import time

from tokenops.control.boundary import emit_observation, observation_from_crossing
from tokenops.control.context import current_governance

from benchmarking.metagpt.action_context import action_scope
from benchmarking.metagpt.governed_llm import wrap_llm
from benchmarking.metagpt.session import current_active_run, record_policy_signal


def _args_summary(args: tuple, kwargs: dict) -> dict:
    if not args:
        return dict(kwargs)
    first = args[0]
    if hasattr(first, "content"):
        return {"instruction": str(getattr(first, "content", ""))[:500]}
    if isinstance(first, str):
        return {"instruction": first[:500]}
    if isinstance(first, list) and first and hasattr(first[0], "content"):
        return {"history_len": len(first), "last": str(first[-1].content)[:200]}
    return {"arg_count": len(args), **kwargs}


def _result_text(result) -> str:
    for attr in ("content", "instruct_content"):
        val = getattr(result, attr, None)
        if val:
            return str(val)[:2000]
    return str(result)[:2000]


class _ActionSnippet:
    def __init__(self, text: str) -> None:
        self.snippet = text
        self.completeness = None


def make_governed_run(original_run):
    async def governed_run(self, *args, **kwargs):
        active = current_active_run()
        name = self.name or self.__class__.__name__
        summary = _args_summary(args, kwargs)
        if getattr(self, "llm", None) is not None and active is not None:
            active.action_llm_id = id(self.llm)
            wrap_llm(self.llm)

        async with action_scope(name=name, args_summary=summary):
            try:
                result = await original_run(self, *args, **kwargs)
            except Exception:
                if active is not None and current_governance() is not None:
                    emit_observation(
                        observation_from_crossing(
                            boundary_id=name,
                            kind="tool",
                            service="metagpt",
                            input_state={"name": name, "args": summary},
                            result=_ActionSnippet(""),
                            ts=time.time(),
                        )
                    )
                raise

        gov_ctx = current_governance()
        if active is not None and gov_ctx is not None:
            controls = active.controls
            override = controls.take_tool_result()
            text = override if override else _result_text(result)
            if override:
                record_policy_signal("tool_fix")
            if override and isinstance(result, str):
                result = override
            emit_observation(
                observation_from_crossing(
                    boundary_id=name,
                    kind="tool",
                    service="metagpt",
                    input_state={"name": name, "args": summary},
                    result=_ActionSnippet(text),
                    ts=time.time(),
                )
            )
        return result

    return governed_run
