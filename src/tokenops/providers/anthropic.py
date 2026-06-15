from __future__ import annotations

import os

import anthropic

from tokenops.providers.types import ModelResponse


def messages(model: str, messages: list[dict[str, str]]) -> ModelResponse:
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    system_parts = [m["content"] for m in messages if m["role"] == "system"]
    user_parts = [m["content"] for m in messages if m["role"] == "user"]
    system = "\n\n".join(system_parts) if system_parts else None
    user = "\n\n".join(user_parts)
    kwargs: dict = {"model": model, "max_tokens": 2048, "messages": [{"role": "user", "content": user}]}
    if system:
        kwargs["system"] = system
    response = client.messages.create(**kwargs)
    usage = response.usage
    text_blocks = [b.text for b in response.content if b.type == "text"]
    return ModelResponse(
        content="".join(text_blocks),
        input_tokens=usage.input_tokens if usage else 0,
        output_tokens=usage.output_tokens if usage else 0,
    )
