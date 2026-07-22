"""Naive researcher agent — tool loop; TokenOps seams live in server.py + tools.py."""

from __future__ import annotations

import json
import re
from dataclasses import replace

from examples.agents.types import CorpusProfile, Finding, StepCallback, StepEvent, TokenUsage
from examples.triad.researcher.prompts import decision_prompt
from examples.triad.researcher.tools import make_fetch_tool, make_search_tool
from examples.app_config import ResearcherServerConfig
from tokenops.control.context import current_governance
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


class ResearcherAgent:
    def __init__(self, config: ResearcherServerConfig) -> None:
        self._config = config

    def run(
        self,
        task: str,
        questions: list[str],
        corpus_profile: CorpusProfile,
        on_step: StepCallback | None = None,
        complete_fn=None,
    ) -> list[Finding]:
        cfg = self._config
        do_complete = complete_fn or complete
        search_fn = make_search_tool(corpus_profile, on_step=on_step)
        fetch_fn = make_fetch_tool(corpus_profile, on_step=on_step)
        context: list[dict] = []
        findings: list[Finding] = []

        for step in range(1, cfg.max_steps + 1):
            messages = [
                {"role": "system", "content": "You are a research agent. Reply with JSON only."},
                {
                    "role": "user",
                    "content": decision_prompt(task, questions, context, cfg.max_steps, step),
                },
            ]
            response = do_complete(cfg.provider, cfg.model, messages)
            if on_step:
                on_step(
                    StepEvent(
                        agent="researcher",
                        action="model",
                        detail="decision",
                        tokens=TokenUsage(response.input_tokens, response.output_tokens),
                    )
                )

            decision = _parse_decision(response.content)
            action = str(decision.get("action", "finish"))
            if action == "finish":
                break

            query = str(decision.get("query") or (questions[0] if questions else task))
            result = fetch_fn(query) if action == "fetch" else search_fn(query)

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
            if result.completeness >= cfg.satisfaction_threshold and len(findings) >= max(1, len(questions)):
                break

        if not findings and questions:
            # Ensure at least one tool crossing so ledger/observations are non-empty in demos.
            result = search_fn(questions[0])
            findings.append(
                Finding(
                    query=result.query,
                    snippet=result.snippet,
                    completeness=result.completeness,
                )
            )

        return findings
