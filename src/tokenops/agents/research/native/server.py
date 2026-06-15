from __future__ import annotations

import asyncio

from tokenops.a2a.client import delegate_summarize
from tokenops.a2a.messages import task_response
from tokenops.a2a.server import create_a2a_app, run_server
from tokenops.agents.research.native.agent import NativeResearchAgent
from tokenops.agents.types import RunResult, StepEvent, TokenUsage
from tokenops.config import load_config


def build_app():
    cfg = load_config().research
    agent = NativeResearchAgent(cfg)
    steps: list[StepEvent] = []
    token_usage = TokenUsage()

    def on_step(event: StepEvent) -> None:
        steps.append(event)
        token_usage.input_tokens += event.tokens.input_tokens
        token_usage.output_tokens += event.tokens.output_tokens

    async def handler(payload: dict) -> dict:
        nonlocal steps, token_usage
        steps = []
        token_usage = TokenUsage()
        task = str(payload.get("task", ""))
        corpus_profile = payload.get("corpus_profile", "healthy")

        findings = await asyncio.to_thread(
            agent.run, task, corpus_profile, on_step
        )

        steps.append(StepEvent(agent="research", action="delegate", detail="calling summarize agent"))
        summary, sum_tokens, sum_steps = await delegate_summarize(
            cfg.summarize_url, task, findings
        )
        token_usage = token_usage.merge(sum_tokens)
        steps.extend(sum_steps)

        result = RunResult(findings=findings, summary=summary, steps=steps, token_usage=token_usage)
        return task_response(result)

    return create_a2a_app(
        name="research-agent",
        description="Research agent (native)",
        base_url=cfg.url,
        skills=["research"],
        handler=handler,
    )


def main() -> None:
    cfg = load_config().research
    run_server(build_app(), cfg.port)


if __name__ == "__main__":
    main()
