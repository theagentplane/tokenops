"""Researcher prompts — decide search vs finish for each question."""

from __future__ import annotations

import json


def decision_prompt(
    task: str,
    questions: list[str],
    context: list[dict],
    max_steps: int,
    step: int,
) -> str:
    context_text = json.dumps(context, indent=2) if context else "[]"
    questions_text = json.dumps(questions, indent=2)
    return f"""You are a research agent gathering facts for a planned outline.

Overall task: {task}
Research questions:
{questions_text}

Step {step} of {max_steps}. Findings so far:
{context_text}

Respond with JSON only:
{{"action": "search", "query": "<search query>"}} OR {{"action": "fetch", "query": "<topic to fetch>"}} OR {{"action": "finish"}}

Search/fetch when you need more information. Finish when findings cover the questions."""
