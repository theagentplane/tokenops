"""A2A-style message helpers for the triad bench."""

from __future__ import annotations

from typing import Any

from examples.a2a.messages import (
    bench_corpus_profile,
    parse_findings,
    parse_steps,
    parse_token_usage,
    task_request,
    task_response,
)
from examples.agents.types import Finding, RunResult, StepEvent, TokenUsage

__all__ = [
    "bench_corpus_profile",
    "task_request",
    "task_response",
    "parse_findings",
    "parse_steps",
    "parse_token_usage",
    "plan_response",
    "research_request",
    "research_response",
    "write_request",
    "write_response",
    "parse_questions",
    "parse_outline",
]


def plan_response(
    *,
    questions: list[str],
    outline: list[str],
    findings: list[Finding],
    answer: str,
    token_usage: TokenUsage | None = None,
    steps: list[StepEvent] | None = None,
) -> dict[str, Any]:
    result = RunResult(
        findings=findings,
        summary=answer,
        steps=steps or [],
        token_usage=token_usage or TokenUsage(),
    )
    body = task_response(result)
    body.update(questions=questions, outline=outline, answer=answer)
    return body


def research_request(
    task: str,
    questions: list[str],
    *,
    outline: list[str] | None = None,
    bench: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "ResearchRequest",
        "task": task,
        "questions": list(questions),
        "outline": list(outline or []),
        "bench": bench or {},
    }


def research_response(
    findings: list[Finding],
    token_usage: TokenUsage | None = None,
    steps: list[StepEvent] | None = None,
    cost_micros: int = 0,
) -> dict[str, Any]:
    return {
        "type": "ResearchResponse",
        "findings": [f.to_dict() for f in findings],
        "token_usage": (token_usage or TokenUsage()).to_dict(),
        "steps": [s.to_dict() for s in (steps or [])],
        "cost_micros": cost_micros,
    }


def write_request(
    task: str,
    findings: list[Finding],
    *,
    outline: list[str] | None = None,
    questions: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "WriteRequest",
        "task": task,
        "findings": [f.to_dict() for f in findings],
        "outline": list(outline or []),
        "questions": list(questions or []),
    }


def write_response(
    answer: str,
    token_usage: TokenUsage | None = None,
    steps: list[StepEvent] | None = None,
    cost_micros: int = 0,
) -> dict[str, Any]:
    return {
        "type": "WriteResponse",
        "answer": answer,
        "summary": answer,
        "token_usage": (token_usage or TokenUsage()).to_dict(),
        "steps": [s.to_dict() for s in (steps or [])],
        "cost_micros": cost_micros,
    }


def parse_questions(data: Any) -> list[str]:
    if not isinstance(data, list):
        return []
    return [str(q).strip() for q in data if str(q).strip()]


def parse_outline(data: Any) -> list[str]:
    if not isinstance(data, list):
        return []
    return [str(item).strip() for item in data if str(item).strip()]
