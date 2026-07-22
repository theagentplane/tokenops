from __future__ import annotations

import json


def summarize_prompt(task: str, findings: list[dict]) -> str:
    return f"""Summarize these research findings for the task.

Task: {task}

Findings:
{json.dumps(findings, indent=2)}

Write a concise summary (3-5 sentences)."""
