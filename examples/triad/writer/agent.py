"""Naive writer agent — single LLM call; TokenOps seams live in server.py."""

from __future__ import annotations

from examples.agents.types import Finding, StepCallback, StepEvent, TokenUsage
from examples.triad.writer.prompts import write_prompt
from examples.app_config import WriterServerConfig
from tokenops.providers import complete


class WriterAgent:
    def __init__(self, config: WriterServerConfig) -> None:
        self._config = config

    def run(
        self,
        task: str,
        findings: list[Finding],
        outline: list[str],
        questions: list[str],
        on_step: StepCallback | None = None,
        complete_fn=None,
    ) -> str:
        cfg = self._config
        do_complete = complete_fn or complete
        messages = [
            {"role": "system", "content": "You are a concise technical writer."},
            {
                "role": "user",
                "content": write_prompt(
                    task,
                    [f.to_dict() for f in findings],
                    outline,
                    questions,
                ),
            },
        ]
        response = do_complete(cfg.provider, cfg.model, messages)
        if on_step:
            on_step(
                StepEvent(
                    agent="writer",
                    action="write",
                    detail="compose final answer",
                    tokens=TokenUsage(response.input_tokens, response.output_tokens),
                )
            )
        return response.content.strip()
