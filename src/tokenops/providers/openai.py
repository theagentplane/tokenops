from __future__ import annotations

import os

from openai import OpenAI

from tokenops.providers.types import ModelResponse


def chat(model: str, messages: list[dict[str, str]], provider: str = "openai") -> ModelResponse:
    if provider == "openai":
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        response = client.chat.completions.create(model=model, messages=messages)
        usage = response.usage
        content = response.choices[0].message.content or ""
        return ModelResponse(
            content=content,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )

    # Anthropic via OpenAI-compatible path not used; delegate to anthropic module
    from tokenops.providers import anthropic as anthropic_provider

    return anthropic_provider.messages(model=model, messages=messages)
