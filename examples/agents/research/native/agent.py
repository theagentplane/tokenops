from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Callable

from tokenops.control.context import current_governance

from examples.agents.research import prompts
from examples.agents.research.tools import core
from examples.agents.types import CorpusProfile, Finding, StepCallback, StepEvent, TokenUsage
from examples.app_config import AgentServerConfig
from chronicle import InputState, boundary
from tokenops.providers import complete


def _parse_decision(content: str) -> dict:
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            return json.loads(match.group())
    return {"action": "finish"}


def make_search_tool(
    profile: CorpusProfile,
    *,
    service: str = "research",
    on_step: StepCallback | None = None,
) -> Callable[[str], core.SearchResult]:
    @boundary(
        "search",
        kind="tool",
        extract_input=lambda query: InputState(
            messages=[], graph_state={"name": "search", "args": {"query": query}}
        ),
    )
    def invoke(query: str) -> core.SearchResult:
        result = core.search(query, profile)
        if on_step:
            on_step(
                StepEvent(
                    agent="research",
                    action="search",
                    detail=result.snippet[:120],
                    query=query,
                    completeness=result.completeness,
                )
            )
        return result

    return invoke


class NativeResearchAgent:
    def __init__(self, config: AgentServerConfig) -> None:
        self._config = config

    def run(
        self,
        task: str,
        corpus_profile: CorpusProfile,
        on_step: StepCallback | None = None,
        complete_fn=None,
        *,
        service: str = "research",
    ) -> list[Finding]:
        cfg = self._config
        do_complete = complete_fn or complete
        search_fn = make_search_tool(corpus_profile, service=service, on_step=on_step)
        context: list[dict] = []
        findings: list[Finding] = []

        for step in range(1, cfg.max_steps + 1):
            messages = [
                {"role": "system", "content": "You are a research agent. Reply with JSON only."},
                {
                    "role": "user",
                    "content": prompts.decision_prompt(task, context, cfg.max_steps, step),
                },
            ]
            response = do_complete(cfg.provider, cfg.model, messages)
            if on_step:
                on_step(
                    StepEvent(
                        agent="research",
                        action="model",
                        detail="decision",
                        tokens=TokenUsage(response.input_tokens, response.output_tokens),
                    )
                )

            decision = _parse_decision(response.content)
            if decision.get("action") == "finish":
                break

            query = str(decision.get("query", task))
            result = search_fn(query)
            # deep INJECT: a tool policy (tool_output_cap / tool_fix) decided during the tool
            # crossing's observe may substitute the result fed into context.
            gov_ctx = current_governance()
            if gov_ctx is not None:
                _controls = getattr(gov_ctx.governor, "controls", None)
                _take = getattr(_controls, "take_tool_result", None)
                _override = _take() if _take else None
                if _override:
                    result = replace(result, snippet=_override)
            entry = {
                "query": result.query,
                "snippet": result.snippet,
                "completeness": result.completeness,
            }
            context.append(entry)
            findings.append(
                Finding(
                    query=result.query,
                    snippet=result.snippet,
                    completeness=result.completeness,
                )
            )
            if result.completeness >= cfg.satisfaction_threshold:
                break

        return findings
