from __future__ import annotations

import os

from openai import OpenAI

from tokenops.providers.types import ModelResponse


def chat(model: str, messages: list[dict[str, str]], provider: str = "openai",
         max_output_tokens: int | None = None) -> ModelResponse:
    if provider == "openai":
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        kwargs: dict = {"model": model, "messages": messages}
        if max_output_tokens is not None:  # TokenOps MUTATE / pre_call_worst_case enforced cap
            kwargs["max_tokens"] = max_output_tokens
        response = client.chat.completions.create(**kwargs)
        usage = response.usage
        content = response.choices[0].message.content or ""
        return ModelResponse(
            content=content,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )

    # Anthropic via OpenAI-compatible path not used; delegate to anthropic module
    from tokenops.providers import anthropic as anthropic_provider

    return anthropic_provider.messages(model=model, messages=messages, max_output_tokens=max_output_tokens)
