from __future__ import annotations

import json


def decision_prompt(task: str, context: list[dict], max_steps: int, step: int) -> str:
    context_text = json.dumps(context, indent=2) if context else "[]"
    return f"""You are a research agent. Task: {task}

Step {step} of {max_steps}. Previous search results:
{context_text}

Respond with JSON only:
{{"action": "search", "query": "<search query>"}} OR {{"action": "finish"}}

Search when you need more information. Finish when findings are sufficient for the task."""
