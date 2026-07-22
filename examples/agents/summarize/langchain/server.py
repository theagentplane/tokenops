from __future__ import annotations

import asyncio

from typing import Mapping

from examples.a2a.messages import parse_findings, summarize_response
from examples.a2a.server import create_a2a_app, run_server
from examples.agents.summarize.langchain.agent import LangChainSummarizeAgent
from examples.agents.types import StepEvent, TokenUsage
from tokenops.control import install_crossing_hook
from examples.app_config import load_config
from tokenops.control import with_governance_errors


def build_app():
    cfg = load_config().summarize
    agent = LangChainSummarizeAgent(cfg)

    async def handler(payload: dict, headers: Mapping[str, str]) -> dict:
        task = str(payload.get("task", ""))
        findings = parse_findings(payload.get("findings", []))
        token_usage = TokenUsage()
        steps: list[StepEvent] = []

        def on_step(event: StepEvent) -> None:
            steps.append(event)
            token_usage.input_tokens += event.tokens.input_tokens
            token_usage.output_tokens += event.tokens.output_tokens

        summary = await asyncio.to_thread(agent.run, task, findings, on_step)
        return summarize_response(summary, token_usage, steps)

    app = create_a2a_app(
        name="summarize-agent",
        description="Summarize agent (langchain)",
        base_url=cfg.url,
        skills=["summarize"],
        handler=with_governance_errors(handler),
    )
    install_crossing_hook()
    return app


def main() -> None:
    cfg = load_config().summarize
    run_server(build_app(), cfg.port)


if __name__ == "__main__":
    main()
