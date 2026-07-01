from __future__ import annotations

from tokenops.providers.types import ModelResponse


def complete(
    provider: str,
    model: str,
    messages: list[dict[str, str]],
    max_output_tokens: int | None = None,
    frequency_penalty: float | None = None,
    presence_penalty: float | None = None,
) -> ModelResponse:
    # Import the provider module lazily so an unused provider's SDK is never a hard
    # dependency (e.g. running OpenAI-only without the anthropic package installed).
    if provider == "anthropic":
        from tokenops.providers import anthropic
        # Anthropic has no frequency/presence penalty knobs; only the cap applies.
        return anthropic.messages(model=model, messages=messages, max_output_tokens=max_output_tokens)
    from tokenops.providers import openai
    return openai.chat(model=model, messages=messages, provider=provider,
                       max_output_tokens=max_output_tokens,
                       frequency_penalty=frequency_penalty, presence_penalty=presence_penalty)


def stream_complete(provider, model, messages, *, max_output_tokens=None,
                    frequency_penalty=None, presence_penalty=None):
    """Yield visible output text chunks. Used by the CANCEL actuator (``wrap_stream``).

    Only OpenAI streaming is implemented; other providers fall back to a single chunk so the
    streaming wrap still functions (CANCEL simply has nothing to tear down)."""
    if provider == "anthropic":
        from tokenops.providers import anthropic
        resp = anthropic.messages(model=model, messages=messages, max_output_tokens=max_output_tokens)
        yield resp.content
        return
    from tokenops.providers import openai
    yield from openai.stream_chat(model, messages, max_output_tokens=max_output_tokens,
                                  frequency_penalty=frequency_penalty, presence_penalty=presence_penalty)
