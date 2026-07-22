from __future__ import annotations

import json
import re

from examples.agents.research import prompts
from examples.agents.research.langchain.tools import make_search_tool
from examples.agents.types import CorpusProfile, Finding, StepCallback, StepEvent, TokenUsage
from examples.app_config import AgentServerConfig


def _get_chat_model(provider: str, model: str):
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=model, temperature=0)
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model=model, temperature=0)


def _parse_decision(content: str) -> dict:
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            return json.loads(match.group())
    return {"action": "finish"}


class LangChainResearchAgent:
    def __init__(self, config: AgentServerConfig) -> None:
        self._config = config
        self._llm = _get_chat_model(config.provider, config.model)

    def run(
        self,
        task: str,
        corpus_profile: CorpusProfile,
        on_step: StepCallback | None = None,
    ) -> list[Finding]:
        cfg = self._config
        search_tool = make_search_tool(corpus_profile, on_step)
        context: list[dict] = []
        findings: list[Finding] = []

        for step in range(1, cfg.max_steps + 1):
            prompt = prompts.decision_prompt(task, context, cfg.max_steps, step)
            response = self._llm.invoke(prompt)
            content = response.content if isinstance(response.content, str) else str(response.content)
            usage = getattr(response, "usage_metadata", None) or {}
            if on_step:
                on_step(
                    StepEvent(
                        agent="research",
                        action="model",
                        detail="decision (langchain)",
                        tokens=TokenUsage(
                            int(usage.get("input_tokens", 0)),
                            int(usage.get("output_tokens", 0)),
                        ),
                    )
                )

            decision = _parse_decision(content)
            if decision.get("action") == "finish":
                break

            query = str(decision.get("query", task))
            result = search_tool.invoke(query)
            entry = result if isinstance(result, dict) else result.to_dict()
            context.append(entry)
            findings.append(
                Finding(
                    query=entry["query"],
                    snippet=entry["snippet"],
                    completeness=float(entry["completeness"]),
                )
            )
            if float(entry["completeness"]) >= cfg.satisfaction_threshold:
                break

        return findings
