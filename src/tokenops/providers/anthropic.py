from __future__ import annotations

import os

import anthropic

from tokenops.providers.types import ModelResponse


def messages(
    model: str, messages: list[dict[str, str]], max_output_tokens: int | None = None
) -> ModelResponse:
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    system_parts = [m["content"] for m in messages if m["role"] == "system"]
    user_parts = [m["content"] for m in messages if m["role"] == "user"]
    system = "\n\n".join(system_parts) if system_parts else None
    user = "\n\n".join(user_parts)
    kwargs: dict = {
        "model": model,
        "max_tokens": max_output_tokens or 2048,
        "messages": [{"role": "user", "content": user}],
    }
    if system:
        kwargs["system"] = system
    response = client.messages.create(**kwargs)
    usage = response.usage
    text_blocks = [b.text for b in response.content if b.type == "text"]
    return ModelResponse(
        content="".join(text_blocks),
        # ModelResponse uses inclusive totals even though the native SDK does not.
        input_tokens=(usage.input_tokens + (getattr(usage, "cache_read_input_tokens", 0) or 0))
        if usage
        else 0,
        cached_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        output_tokens=usage.output_tokens if usage else 0,
    )
