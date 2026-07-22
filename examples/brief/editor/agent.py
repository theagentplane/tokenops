"""LangChain editor agent — TokenOps via GovernedChatModel injected from server.py."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from examples.agents.types import Finding, StepCallback, StepEvent, TokenUsage
from examples.app_config import EditorServerConfig
from examples.brief.editor.prompts import edit_prompt
from examples.brief.langchain_bridge import GovernedChatModel, get_chat_model


class EditorAgent:
    def __init__(self, config: EditorServerConfig) -> None:
        self._config = config
        self._fallback_llm = get_chat_model(config.provider, config.model)

    def run(
        self,
        topic: str,
        findings: list[Finding],
        sections: list[str],
        angles: list[str],
        on_step: StepCallback | None = None,
        llm: Any = None,
        complete_fn=None,
    ) -> str:
        cfg = self._config
        if llm is None and complete_fn is not None:
            llm = GovernedChatModel(complete_fn, provider=cfg.provider, model=cfg.model)
        chat = llm or self._fallback_llm

        messages = [
            SystemMessage(content="You are a concise executive brief editor."),
            HumanMessage(
                content=edit_prompt(
                    topic,
                    [f.to_dict() for f in findings],
                    sections,
                    angles,
                ),
            ),
        ]
        response = chat.invoke(messages)
        content = response.content if isinstance(response.content, str) else str(response.content)
        usage = getattr(response, "usage_metadata", None) or {}
        if on_step:
            on_step(
                StepEvent(
                    agent="editor",
                    action="edit",
                    detail="compose executive brief (langchain)",
                    tokens=TokenUsage(
                        int(usage.get("input_tokens", 0) or 0),
                        int(usage.get("output_tokens", 0) or 0),
                    ),
                )
            )
        return content.strip()
