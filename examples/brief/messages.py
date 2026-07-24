"""A2A message helpers for the brief stack (Scout → Analyst → Editor)."""

from __future__ import annotations

from typing import Any

from examples.a2a.messages import task_response
from examples.agents.types import Finding, RunResult, StepEvent, TokenUsage


def scout_response(
    *,
    angles: list[str],
    sections: list[str],
    findings: list[Finding],
    brief: str,
    token_usage: TokenUsage | None = None,
    steps: list[StepEvent] | None = None,
) -> dict[str, Any]:
    result = RunResult(
        findings=findings,
        summary=brief,
        steps=steps or [],
        token_usage=token_usage or TokenUsage(),
    )
    body = task_response(result)
    body.update(angles=angles, sections=sections, answer=brief, brief=brief)
    return body


def analyze_request(
    topic: str,
    angles: list[str],
    *,
    sections: list[str] | None = None,
    bench: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "AnalyzeRequest",
        "task": topic,
        "angles": list(angles),
        "sections": list(sections or []),
        "bench": bench or {},
    }


def analyze_response(
    findings: list[Finding],
    token_usage: TokenUsage | None = None,
    steps: list[StepEvent] | None = None,
    cost_micros: int = 0,
) -> dict[str, Any]:
    return {
        "type": "AnalyzeResponse",
        "findings": [f.to_dict() for f in findings],
        "token_usage": (token_usage or TokenUsage()).to_dict(),
        "steps": [s.to_dict() for s in (steps or [])],
        "cost_micros": cost_micros,
    }


def edit_request(
    topic: str,
    findings: list[Finding],
    *,
    sections: list[str] | None = None,
    angles: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "EditRequest",
        "task": topic,
        "findings": [f.to_dict() for f in findings],
        "sections": list(sections or []),
        "angles": list(angles or []),
    }


def edit_response(
    brief: str,
    token_usage: TokenUsage | None = None,
    steps: list[StepEvent] | None = None,
    cost_micros: int = 0,
) -> dict[str, Any]:
    return {
        "type": "EditResponse",
        "brief": brief,
        "answer": brief,
        "summary": brief,
        "token_usage": (token_usage or TokenUsage()).to_dict(),
        "steps": [s.to_dict() for s in (steps or [])],
        "cost_micros": cost_micros,
    }


def parse_angles(data: Any) -> list[str]:
    if not isinstance(data, list):
        return []
    return [str(a).strip() for a in data if str(a).strip()]


def parse_sections(data: Any) -> list[str]:
    if not isinstance(data, list):
        return []
    return [str(s).strip() for s in data if str(s).strip()]
