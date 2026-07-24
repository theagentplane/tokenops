"""Compress a run window into a lean trajectory summary for hint injection."""

from __future__ import annotations

import json
from collections.abc import Sequence

from tokenops.control.core import BoundaryStep


def compress_trajectory(steps: Sequence[BoundaryStep]) -> tuple[str, str]:
    """Return ``(step_summary, tool_sequence)`` from a completed run window."""
    tool_parts: list[str] = []
    llm_count = 0
    last_llm_text = ""

    for step in steps:
        if step.node_type == "tool":
            args = step.input.get("args", {}) if isinstance(step.input, dict) else {}
            arg_str = json.dumps(args, sort_keys=True, default=str)
            if len(arg_str) > 80:
                arg_str = arg_str[:77] + "..."
            tool_parts.append(f"{step.boundary_id}({arg_str})")
        elif step.node_type == "llm":
            llm_count += 1
            if isinstance(step.output, dict):
                text = step.output.get("text", "")
                if text:
                    last_llm_text = str(text)

    tool_sequence = " → ".join(tool_parts) if tool_parts else "(no tool steps)"

    summary_lines = [
        f"Tool sequence ({len(tool_parts)} calls): {tool_sequence}.",
        f"LLM steps: {llm_count}.",
    ]
    if last_llm_text:
        preview = last_llm_text.replace("\n", " ")
        if len(preview) > 200:
            preview = preview[:197] + "..."
        summary_lines.append(f"Final output shape: {preview}")

    return "\n".join(summary_lines), tool_sequence
