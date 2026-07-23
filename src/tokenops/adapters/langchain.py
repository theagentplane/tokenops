"""LangChain ↔ TokenOps bridge.

``wrap_complete`` expects ``complete(provider, model, messages, **kwargs) → ModelResponse``.
LangChain agents expect a ``BaseChatModel``. This module connects them so pre_call /
observe / HALT still run while the agent code uses LangChain APIs.

Requires optional extra: ``pip install agent-tokenops[examples]`` (langchain-core, …).
"""

from __future__ import annotations

from typing import Any, Callable, Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ConfigDict, PrivateAttr

from tokenops.providers.types import ModelResponse

DispatchFn = Callable[..., ModelResponse]


def get_chat_model(provider: str, model: str) -> BaseChatModel:
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=model, temperature=0)
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model=model, temperature=0)


def to_lc_messages(messages: Sequence[dict[str, str]]) -> list[BaseMessage]:
    out: list[BaseMessage] = []
    for msg in messages:
        role = str(msg.get("role", "user"))
        content = str(msg.get("content", ""))
        if role == "system":
            out.append(SystemMessage(content=content))
        elif role == "assistant":
            out.append(AIMessage(content=content))
        else:
            out.append(HumanMessage(content=content))
    return out


def from_lc_messages(messages: Sequence[BaseMessage]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            role = "system"
        elif isinstance(msg, AIMessage):
            role = "assistant"
        else:
            role = "user"
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        out.append({"role": role, "content": content})
    return out


# Back-compat aliases used by examples/brief
_to_lc_messages = to_lc_messages
_from_lc_messages = from_lc_messages


def make_langchain_dispatch(provider: str, model: str) -> DispatchFn:
    """Real LLM calls go through LangChain; return type matches ``tokenops.providers.complete``."""
    llm = get_chat_model(provider, model)

    def dispatch(
        _provider: str,
        use_model: str,
        messages: Sequence[dict[str, str]],
        max_output_tokens: int | None = None,
        **_kwargs: Any,
    ) -> ModelResponse:
        chat = llm
        if use_model != model:
            chat = get_chat_model(provider, use_model)
        bound = chat
        if max_output_tokens is not None and hasattr(chat, "bind"):
            try:
                bound = chat.bind(max_tokens=max_output_tokens)
            except Exception:
                bound = chat
        response = bound.invoke(to_lc_messages(messages))
        content = response.content if isinstance(response.content, str) else str(response.content)
        usage = getattr(response, "usage_metadata", None) or {}
        return ModelResponse(
            content=content,
            input_tokens=int(usage.get("input_tokens", 0) or 0),
            output_tokens=int(usage.get("output_tokens", 0) or 0),
        )

    return dispatch


class GovernedChatModel(BaseChatModel):
    """LangChain chat model whose every invoke goes through ``wrap_complete``."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    provider: str = "openai"
    model_name: str = "gpt-4o-mini"
    _complete_fn: Callable[..., Any] = PrivateAttr()

    def __init__(
        self,
        complete_fn: Callable[..., Any],
        *,
        provider: str,
        model: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(provider=provider, model_name=model, **kwargs)
        self._complete_fn = complete_fn

    @property
    def _llm_type(self) -> str:
        return "tokenops-governed-langchain"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        dicts = from_lc_messages(messages)
        resp = self._complete_fn(self.provider, self.model_name, dicts)
        content = getattr(resp, "content", str(resp))
        inp = int(getattr(resp, "input_tokens", 0) or 0)
        out = int(getattr(resp, "output_tokens", 0) or 0)
        usage = {
            "input_tokens": inp,
            "output_tokens": out,
            "total_tokens": inp + out,
        }
        message = AIMessage(content=content, usage_metadata=usage)
        return ChatResult(generations=[ChatGeneration(message=message)])
