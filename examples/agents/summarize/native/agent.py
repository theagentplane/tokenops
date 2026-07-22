from __future__ import annotations

from examples.agents.summarize.prompts import summarize_prompt
from examples.agents.types import Finding, StepCallback, StepEvent, TokenUsage
from examples.app_config import SummarizeServerConfig
from tokenops.providers import complete


class NativeSummarizeAgent:
    def __init__(self, config: SummarizeServerConfig) -> None:
        self._config = config

    def run(
        self,
        task: str,
        findings: list[Finding],
        on_step: StepCallback | None = None,
        complete_fn=None,
    ) -> str:
        cfg = self._config
        do_complete = complete_fn or complete  # governed wrapper or vanilla provider entry
        finding_dicts = [f.to_dict() for f in findings]
        messages = [
            {"role": "system", "content": "You are a concise summarizer."},
            {"role": "user", "content": summarize_prompt(task, finding_dicts)},
        ]
        response = do_complete(cfg.provider, cfg.model, messages)
        if on_step:
            on_step(
                StepEvent(
                    agent="summarize",
                    action="model",
                    detail="summarize findings",
                    tokens=TokenUsage(response.input_tokens, response.output_tokens),
                )
            )
        return response.content.strip()
