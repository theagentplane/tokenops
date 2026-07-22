"""Naive planner agent — LLM-only; TokenOps seams live in server.py."""

from __future__ import annotations

import json
import re
from typing import Any

from examples.agents.types import StepCallback, StepEvent, TokenUsage
from examples.triad.planner.prompts import plan_prompt
from examples.app_config import PlannerServerConfig
from tokenops.providers import complete


def _parse_plan(content: str) -> tuple[list[str], list[str]]:
    text = content.strip()
    data: dict[str, Any]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return [text[:200] or "clarify the goal"], ["Introduction", "Findings", "Conclusion"]
        data = json.loads(match.group())
    questions = [str(q).strip() for q in (data.get("questions") or []) if str(q).strip()]
    outline = [str(o).strip() for o in (data.get("outline") or []) if str(o).strip()]
    if not questions:
        questions = ["What are the key facts for this goal?"]
    if not outline:
        outline = ["Background", "Key findings", "Summary"]
    return questions, outline


class PlannerAgent:
    def __init__(self, config: PlannerServerConfig) -> None:
        self._config = config

    def run(
        self,
        goal: str,
        on_step: StepCallback | None = None,
        complete_fn=None,
    ) -> tuple[list[str], list[str]]:
        cfg = self._config
        do_complete = complete_fn or complete
        messages = [
            {"role": "system", "content": "You are a planning agent. Reply with JSON only."},
            {"role": "user", "content": plan_prompt(goal, cfg.max_questions)},
        ]
        response = do_complete(cfg.provider, cfg.model, messages)
        if on_step:
            on_step(
                StepEvent(
                    agent="planner",
                    action="plan",
                    detail="produce questions + outline",
                    tokens=TokenUsage(response.input_tokens, response.output_tokens),
                )
            )
        questions, outline = _parse_plan(response.content)
        return questions[: cfg.max_questions], outline
