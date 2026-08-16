from __future__ import annotations

from typing import Any

from tokenops.agents.types import Finding, RunResult, StepEvent, TokenUsage


def task_request(task: str, corpus_profile: str, run_id: str | None = None,
                 user: str = "ui") -> dict[str, Any]:
    msg: dict[str, Any] = {"type": "TaskRequest", "task": task, "corpus_profile": corpus_profile,
                           "user": user}
    if run_id is not None:
        msg["run_id"] = run_id  # else the research boundary generates one
    return msg


def task_response(result: RunResult) -> dict[str, Any]:
    return {"type": "TaskResponse", **result.to_dict()}


def summarize_request(task: str, findings: list[Finding], parent_run: str | None = None,
                      user: str = "ui") -> dict[str, Any]:
    return {
        "type": "SummarizeRequest",
        "task": task,
        "findings": [f.to_dict() for f in findings],
        "parent_run": parent_run,  # the research run_id this delegation belongs to
        "user": user,
    }


def parse_steps(data: list[dict[str, Any]]) -> list[StepEvent]:
    return [
        StepEvent(
            agent=s["agent"],
            action=s["action"],
            detail=s.get("detail", ""),
            query=s.get("query", ""),
            completeness=s.get("completeness"),
            tokens=parse_token_usage(s.get("tokens")),
        )
        for s in data
    ]


def summarize_response(
    summary: str,
    token_usage: TokenUsage | None = None,
    steps: list[StepEvent] | None = None,
    cost_micros: int = 0,
) -> dict[str, Any]:
    step_list = steps or []
    return {
        "type": "SummarizeResponse",
        "summary": summary,
        "token_usage": (token_usage or TokenUsage()).to_dict(),
        "steps": [s.to_dict() for s in step_list],
        "cost_micros": cost_micros,  # child run total, rolled up to the parent
    }


def parse_findings(data: list[dict[str, Any]]) -> list[Finding]:
    return [Finding.from_dict(item) for item in data]


def parse_token_usage(data: dict[str, Any] | None) -> TokenUsage:
    if not data:
        return TokenUsage()
    return TokenUsage(
        input_tokens=int(data.get("input_tokens", 0)),
        output_tokens=int(data.get("output_tokens", 0)),
    )
