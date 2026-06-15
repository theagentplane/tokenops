from __future__ import annotations

from tokenops.providers import anthropic, openai
from tokenops.providers.types import ModelResponse


def complete(
    provider: str,
    model: str,
    messages: list[dict[str, str]],
) -> ModelResponse:
    if provider == "anthropic":
        return anthropic.messages(model=model, messages=messages)
    return openai.chat(model=model, messages=messages, provider=provider)
