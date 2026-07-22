"""LangChain scout agent — TokenOps via GovernedChatModel injected from server.py."""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from examples.agents.types import StepCallback, StepEvent, TokenUsage
from examples.app_config import ScoutServerConfig
from examples.brief.langchain_bridge import GovernedChatModel, get_chat_model
from examples.brief.scout.prompts import scout_prompt


def _parse_scout(content: str) -> tuple[list[str], list[str]]:
    text = content.strip()
    data: dict[str, Any]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return [text[:200] or "clarify the topic"], ["Overview", "Signals", "Takeaways"]
        data = json.loads(match.group())
    angles = [str(a).strip() for a in (data.get("angles") or []) if str(a).strip()]
    sections = [str(s).strip() for s in (data.get("sections") or []) if str(s).strip()]
    if not angles:
        angles = ["What are the key market signals for this topic?"]
    if not sections:
        sections = ["Overview", "Evidence", "Recommendation"]
    return angles, sections


class ScoutAgent:
    """LangChain chat agent. Pass a ``GovernedChatModel`` from the server for TokenOps."""

    def __init__(self, config: ScoutServerConfig) -> None:
        self._config = config
        self._fallback_llm = get_chat_model(config.provider, config.model)

    def run(
        self,
        topic: str,
        on_step: StepCallback | None = None,
        llm: Any = None,
        complete_fn=None,
    ) -> tuple[list[str], list[str]]:
        cfg = self._config
        if llm is None and complete_fn is not None:
            llm = GovernedChatModel(complete_fn, provider=cfg.provider, model=cfg.model)
        chat = llm or self._fallback_llm

        messages = [
            SystemMessage(content="You are a scouting agent. Reply with JSON only."),
            HumanMessage(content=scout_prompt(topic, cfg.max_angles)),
        ]
        response = chat.invoke(messages)
        content = response.content if isinstance(response.content, str) else str(response.content)
        usage = getattr(response, "usage_metadata", None) or {}
        if on_step:
            on_step(
                StepEvent(
                    agent="scout",
                    action="scout",
                    detail="produce angles + sections (langchain)",
                    tokens=TokenUsage(
                        int(usage.get("input_tokens", 0) or 0),
                        int(usage.get("output_tokens", 0) or 0),
                    ),
                )
            )
        angles, sections = _parse_scout(content)
        return angles[: cfg.max_angles], sections
