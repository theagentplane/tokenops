"""Lean envelope shapes — Chronicle-compatible input/result capture."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class InputState:
    messages: list[dict[str, Any]] = field(default_factory=list)
    system_prompt: str | None = None
    graph_state: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCall:
    id: str | None = None
    name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ActionResult:
    tool_calls: list[ToolCall] = field(default_factory=list)
    completion: str | None = None
    finish_reason: str | None = None
    raw_response: Any | None = None
