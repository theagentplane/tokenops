"""LangChain ↔ TokenOps bridge for the brief stack.

Re-exports the shared adapter in ``tokenops.adapters.langchain`` so brief servers
keep stable import paths.
"""

from __future__ import annotations

from tokenops.adapters.langchain import (  # noqa: F401
    GovernedChatModel,
    get_chat_model,
    make_langchain_dispatch,
)

__all__ = [
    "GovernedChatModel",
    "get_chat_model",
    "make_langchain_dispatch",
]
