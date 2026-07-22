from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

from examples.agents.summarize.prompts import summarize_prompt
from examples.agents.types import Finding, StepCallback, StepEvent, TokenUsage
from examples.app_config import SummarizeServerConfig


def _get_chat_model(provider: str, model: str):
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=model, temperature=0)
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model=model, temperature=0)


class LangChainSummarizeAgent:
    def __init__(self, config: SummarizeServerConfig) -> None:
        self._config = config
        self._llm = _get_chat_model(config.provider, config.model)
        self._chain = ChatPromptTemplate.from_messages(
            [
                ("system", "You are a concise summarizer."),
                ("user", "{prompt}"),
            ]
        ) | self._llm

    def run(
        self,
        task: str,
        findings: list[Finding],
        on_step: StepCallback | None = None,
    ) -> str:
        finding_dicts = [f.to_dict() for f in findings]
        prompt = summarize_prompt(task, finding_dicts)
        response = self._chain.invoke({"prompt": prompt})
        content = response.content if isinstance(response.content, str) else str(response.content)
        usage = getattr(response, "usage_metadata", None) or {}
        if on_step:
            on_step(
                StepEvent(
                    agent="summarize",
                    action="model",
                    detail="summarize (langchain)",
                    tokens=TokenUsage(
                        int(usage.get("input_tokens", 0)),
                        int(usage.get("output_tokens", 0)),
                    ),
                )
            )
        return content.strip()
