from __future__ import annotations

import asyncio

from typing import Mapping

from examples.a2a.client import delegate_summarize
from examples.a2a.messages import bench_corpus_profile, task_response
from examples.a2a.server import create_a2a_app, run_server
from examples.agents.research.langchain.agent import LangChainResearchAgent
from examples.agents.types import RunResult, StepEvent, TokenUsage
from tokenops.control import install_crossing_hook
from examples.app_config import load_config
from tokenops.control import with_governance_errors


def build_app():
    cfg = load_config().research
    agent = LangChainResearchAgent(cfg)
    steps: list[StepEvent] = []
    token_usage = TokenUsage()

    def on_step(event: StepEvent) -> None:
        steps.append(event)
        token_usage.input_tokens += event.tokens.input_tokens
        token_usage.output_tokens += event.tokens.output_tokens

    async def handler(payload: dict, headers: Mapping[str, str]) -> dict:
        nonlocal steps, token_usage
        steps = []
        token_usage = TokenUsage()
        task = str(payload.get("task", ""))
        corpus_profile = bench_corpus_profile(payload)

        findings = await asyncio.to_thread(agent.run, task, corpus_profile, on_step)
        steps.append(StepEvent(agent="research", action="delegate", detail="calling summarize agent"))
        summary, sum_tokens, sum_steps, _sum_cost = await delegate_summarize(
            cfg.summarize_url, task, findings,
        )
        token_usage = token_usage.merge(sum_tokens)
        steps.extend(sum_steps)
        return task_response(RunResult(findings=findings, summary=summary, steps=steps, token_usage=token_usage))

    app = create_a2a_app(
        name="research-agent",
        description="Research agent (langchain)",
        base_url=cfg.url,
        skills=["research"],
        handler=with_governance_errors(handler),
    )
    install_crossing_hook()
    return app


def main() -> None:
    cfg = load_config().research
    run_server(build_app(), cfg.port)


if __name__ == "__main__":
    main()
