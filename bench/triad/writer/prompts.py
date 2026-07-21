"""Writer prompts — final answer from findings + outline."""

from __future__ import annotations

import json


def write_prompt(
    task: str,
    findings: list[dict],
    outline: list[str],
    questions: list[str],
) -> str:
    return f"""You are a writer agent. Produce a clear final answer for the user goal.

Goal: {task}

Outline:
{json.dumps(outline, indent=2)}

Research questions:
{json.dumps(questions, indent=2)}

Findings:
{json.dumps(findings, indent=2)}

Write a concise answer that follows the outline and cites the findings. Plain text only."""
