"""Scope nested action LLM calls to the parent ``Action.run``."""

from __future__ import annotations

from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class ActionContext:
    name: str
    args_summary: dict


_action: ContextVar[ActionContext | None] = ContextVar("metagpt_action_ctx", default=None)


def current_action() -> ActionContext | None:
    return _action.get()


@asynccontextmanager
async def action_scope(*, name: str, args_summary: dict | None = None):
    token = _action.set(ActionContext(name=name, args_summary=args_summary or {}))
    try:
        yield
    finally:
        _action.reset(token)
