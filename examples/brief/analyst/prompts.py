"""Analyst prompts — decide search vs finish for each angle."""

from __future__ import annotations

import json


def decision_prompt(
    topic: str,
    angles: list[str],
    context: list[dict],
    max_steps: int,
    step: int,
) -> str:
    context_text = json.dumps(context, indent=2) if context else "[]"
    angles_text = json.dumps(angles, indent=2)
    return f"""You are an analyst gathering evidence for a market brief.

Topic: {topic}
Angles:
{angles_text}

Step {step} of {max_steps}. Evidence so far:
{context_text}

Respond with JSON only:
{{"action": "search", "query": "<search query>"}} OR {{"action": "fetch", "query": "<topic to fetch>"}} OR {{"action": "finish"}}

Search/fetch when you need more evidence. Finish when angles are covered."""
