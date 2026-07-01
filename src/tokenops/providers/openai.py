from __future__ import annotations

import os

from openai import OpenAI

from tokenops.providers.types import ModelResponse


def chat(model: str, messages: list[dict[str, str]], provider: str = "openai",
         max_output_tokens: int | None = None,
         frequency_penalty: float | None = None,
         presence_penalty: float | None = None) -> ModelResponse:
    if provider == "openai":
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        kwargs: dict = {"model": model, "messages": messages}
        if max_output_tokens is not None:  # TokenOps MUTATE / pre_call_worst_case enforced cap
            kwargs["max_tokens"] = max_output_tokens
        if frequency_penalty is not None:  # output_runaway RETRY: raise anti-repetition penalty
            kwargs["frequency_penalty"] = frequency_penalty
        if presence_penalty is not None:
            kwargs["presence_penalty"] = presence_penalty
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


def stream_chat(model: str, messages: list[dict[str, str]], *,
                max_output_tokens: int | None = None,
                frequency_penalty: float | None = None,
                presence_penalty: float | None = None):
    """Yield visible output text chunks as they stream. The control plane's CANCEL tears
    this generator down mid-flight (``generator.close()``) to stop a runaway bleed."""
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    kwargs: dict = {"model": model, "messages": messages, "stream": True}
    if max_output_tokens is not None:
        kwargs["max_tokens"] = max_output_tokens
    if frequency_penalty is not None:
        kwargs["frequency_penalty"] = frequency_penalty
    if presence_penalty is not None:
        kwargs["presence_penalty"] = presence_penalty
    for chunk in client.chat.completions.create(**kwargs):
        if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content
