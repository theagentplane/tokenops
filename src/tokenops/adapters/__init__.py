"""Cross-platform LLM adapters for ``wrap_complete``.

TokenOps governs a single dispatch shape
``complete(provider, model, messages, **kwargs) → ModelResponse``.
Adapters bridge that to framework-native model nodes (e.g. LangChain
``BaseChatModel``) without forking ``wrap_complete``.

Import submodules explicitly (``tokenops.adapters.langchain``) so core TokenOps
does not pull optional LangChain deps at package import time.
"""

from __future__ import annotations

__all__ = [
    "GovernedChatModel",
    "get_chat_model",
    "make_langchain_dispatch",
]


def __getattr__(name: str):
    if name in __all__:
        from tokenops.adapters import langchain as _lc

        return getattr(_lc, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
