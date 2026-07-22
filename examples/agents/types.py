from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

CorpusProfile = Literal["healthy", "leak"]
Framework = Literal["native", "langchain"]

StepCallback = Callable[["StepEvent"], None]


@dataclass
class Finding:
    query: str
    snippet: str
    completeness: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "snippet": self.snippet,
            "completeness": self.completeness,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Finding:
        return cls(
            query=str(data["query"]),
            snippet=str(data["snippet"]),
            completeness=float(data["completeness"]),
        )


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    def to_dict(self) -> dict[str, int]:
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens}

    def merge(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
        )


@dataclass
class StepEvent:
    agent: Literal["research", "summarize", "planner", "researcher", "writer"]
    action: Literal["model", "search", "fetch", "delegate", "plan", "write"]
    detail: str = ""
    query: str = ""
    completeness: float | None = None
    tokens: TokenUsage = field(default_factory=TokenUsage)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "action": self.action,
            "detail": self.detail,
            "query": self.query,
            "completeness": self.completeness,
            "tokens": self.tokens.to_dict(),
        }

    def display_row(self) -> dict[str, Any]:
        """Flat row for Streamlit tables (nested dicts do not render)."""
        return {
            "agent": self.agent,
            "action": self.action,
            "detail": self.detail,
            "query": self.query,
            "completeness": self.completeness,
            "input_tokens": self.tokens.input_tokens,
            "output_tokens": self.tokens.output_tokens,
        }


@dataclass
class RunResult:
    findings: list[Finding]
    summary: str
    steps: list[StepEvent] = field(default_factory=list)
    token_usage: TokenUsage = field(default_factory=TokenUsage)

    def to_dict(self) -> dict[str, Any]:
        return {
            "findings": [f.to_dict() for f in self.findings],
            "summary": self.summary,
            "steps": [s.to_dict() for s in self.steps],
            "token_usage": self.token_usage.to_dict(),
        }
