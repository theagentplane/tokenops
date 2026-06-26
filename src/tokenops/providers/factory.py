from __future__ import annotations

from tokenops.providers.types import ModelResponse


def complete(
    provider: str,
    model: str,
    messages: list[dict[str, str]],
    max_output_tokens: int | None = None,
) -> ModelResponse:
    # Import the provider module lazily so an unused provider's SDK is never a hard
    # dependency (e.g. running OpenAI-only without the anthropic package installed).
    if provider == "anthropic":
        from tokenops.providers import anthropic
        return anthropic.messages(model=model, messages=messages, max_output_tokens=max_output_tokens)
    from tokenops.providers import openai
    return openai.chat(model=model, messages=messages, provider=provider,
                       max_output_tokens=max_output_tokens)
