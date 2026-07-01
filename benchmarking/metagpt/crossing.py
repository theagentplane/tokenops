"""Resolve LLM crossing metadata from run + action context."""

from __future__ import annotations

from benchmarking.metagpt.action_context import current_action
from benchmarking.metagpt.session import ActiveRun


def resolve_llm_crossing(
    llm,
    active: ActiveRun | None,
    messages,
) -> tuple[str, dict, dict[str, str]]:
    base = {"message_count": len(messages) if messages else 0}
    tags: dict[str, str] = {"node_type": "llm"}

    act = current_action()
    if act is not None and active is not None and active.action_llm_id == id(llm):
        tags["parent_action"] = act.name
        tags["tool"] = act.name
        return (
            "metagpt.action.llm",
            {**base, "action": act.name, **act.args_summary, "parent_action": act.name},
            tags,
        )

    if active is not None and active.think_llm_id == id(llm):
        tags["role"] = "think"
        return ("metagpt.think", base, tags)

    tagged = getattr(llm, "_tokenops_boundary_id", None)
    if tagged:
        return (str(tagged), base, tags)

    model = getattr(llm, "model", None) or getattr(getattr(llm, "config", None), "model", "llm")
    return (f"metagpt.{model}", base, tags)
