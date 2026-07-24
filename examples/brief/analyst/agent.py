"""LangChain analyst agent — tool loop; TokenOps via GovernedChatModel + @boundary tools."""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from examples.agents.types import CorpusProfile, Finding, StepCallback, StepEvent, TokenUsage
from examples.app_config import AnalystServerConfig
from examples.brief.analyst.prompts import decision_prompt
from examples.brief.analyst.tools import make_fetch_tool, make_search_tool
from examples.brief.langchain_bridge import GovernedChatModel, get_chat_model
from tokenops.control.context import current_governance


def _parse_decision(content: str) -> dict:
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            return json.loads(match.group())
    return {"action": "finish"}


class AnalystAgent:
    def __init__(self, config: AnalystServerConfig) -> None:
        self._config = config
        self._fallback_llm = get_chat_model(config.provider, config.model)

    def run(
        self,
        topic: str,
        angles: list[str],
        corpus_profile: CorpusProfile,
        on_step: StepCallback | None = None,
        llm: Any = None,
        complete_fn=None,
    ) -> list[Finding]:
        cfg = self._config
        if llm is None and complete_fn is not None:
            llm = GovernedChatModel(complete_fn, provider=cfg.provider, model=cfg.model)
        chat = llm or self._fallback_llm

        search_tool = make_search_tool(corpus_profile, on_step=on_step)
        fetch_tool = make_fetch_tool(corpus_profile, on_step=on_step)
        context: list[dict] = []
        findings: list[Finding] = []

        for step in range(1, cfg.max_steps + 1):
            messages = [
                SystemMessage(content="You are an analyst agent. Reply with JSON only."),
                HumanMessage(
                    content=decision_prompt(topic, angles, context, cfg.max_steps, step),
                ),
            ]
            response = chat.invoke(messages)
            content = (
                response.content if isinstance(response.content, str) else str(response.content)
            )
            usage = getattr(response, "usage_metadata", None) or {}
            if on_step:
                on_step(
                    StepEvent(
                        agent="analyst",
                        action="model",
                        detail="decision (langchain)",
                        tokens=TokenUsage(
                            int(usage.get("input_tokens", 0) or 0),
                            int(usage.get("output_tokens", 0) or 0),
                        ),
                    )
                )

            decision = _parse_decision(content)
            action = str(decision.get("action", "finish"))
            if action == "finish":
                break

            query = str(decision.get("query") or (angles[0] if angles else topic))
            raw = fetch_tool.invoke(query) if action == "fetch" else search_tool.invoke(query)
            entry = (
                raw
                if isinstance(raw, dict)
                else {"query": query, "snippet": str(raw), "completeness": 0.5}
            )

            gov_ctx = current_governance()
            if gov_ctx is not None:
                _controls = getattr(gov_ctx.governor, "controls", None)
                _take = getattr(_controls, "take_tool_result", None)
                _override = _take() if _take else None
                if _override:
                    entry = {**entry, "snippet": _override}

            context.append(entry)
            findings.append(
                Finding(
                    query=str(entry.get("query", query)),
                    snippet=str(entry.get("snippet", "")),
                    completeness=float(entry.get("completeness", 0.0)),
                )
            )
            if float(entry.get("completeness", 0)) >= cfg.satisfaction_threshold and len(
                findings
            ) >= max(1, len(angles)):
                break

        if not findings and angles:
            entry = search_tool.invoke(angles[0])
            if not isinstance(entry, dict):
                entry = {"query": angles[0], "snippet": str(entry), "completeness": 0.5}
            findings.append(
                Finding(
                    query=str(entry.get("query", angles[0])),
                    snippet=str(entry.get("snippet", "")),
                    completeness=float(entry.get("completeness", 0.0)),
                )
            )

        return findings
