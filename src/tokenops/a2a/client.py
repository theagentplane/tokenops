from __future__ import annotations

from tokenops.a2a import messages
from tokenops.a2a.server import fetch_agent_card, fetch_agent_card_sync, post_run_sync, post_task, post_task_sync
from tokenops.agents.types import Finding, RunResult, StepEvent, TokenUsage
from tokenops.a2a.messages import parse_findings, parse_token_usage, summarize_request, parse_steps
from tokenops.control.context import PARENT_SPAN_ID_HEADER, RUN_ID_HEADER


def _parse_run_result(data: dict) -> RunResult:
    findings = parse_findings(data.get("findings", []))
    steps = parse_steps(data.get("steps", []))
    return RunResult(
        findings=findings,
        summary=str(data.get("summary", "")),
        steps=steps,
        token_usage=parse_token_usage(data.get("token_usage")),
    )


def submit_task_sync(
    research_url: str,
    task: str,
    *,
    corpus_profile: str = "healthy",
    intent: str = "",
    user_dims: dict[str, str] | None = None,
) -> RunResult:
    reg = post_run_sync(
        research_url,
        {"intent": intent, "user_dims": user_dims or {}},
    )
    run_id = reg["run_id"]
    payload = messages.task_request(task=task, bench={"corpus_profile": corpus_profile})
    data = post_task_sync(research_url, payload, headers={RUN_ID_HEADER: run_id})
    return _parse_run_result(data)


async def submit_task(
    research_url: str,
    task: str,
    *,
    corpus_profile: str = "healthy",
    intent: str = "",
    user_dims: dict[str, str] | None = None,
) -> RunResult:
    from tokenops.a2a.server import post_run

    reg = await post_run(research_url, {"intent": intent, "user_dims": user_dims or {}})
    run_id = reg["run_id"]
    payload = messages.task_request(task=task, bench={"corpus_profile": corpus_profile})
    data = await post_task(research_url, payload, headers={RUN_ID_HEADER: run_id})
    return _parse_run_result(data)


async def delegate_summarize(
    summarize_url: str,
    task: str,
    findings: list[Finding],
    *,
    run_id: str,
    parent_span_id: str | None = None,
) -> tuple[str, TokenUsage, list[StepEvent], int]:
    payload = summarize_request(task=task, findings=findings)
    headers = {RUN_ID_HEADER: run_id}
    if parent_span_id:
        headers[PARENT_SPAN_ID_HEADER] = parent_span_id
    data = await post_task(summarize_url, payload, headers=headers)
    return (
        str(data.get("summary", "")),
        parse_token_usage(data.get("token_usage")),
        parse_steps(data.get("steps", [])),
        int(data.get("cost_micros", 0)),
    )


def check_health_sync(url: str) -> bool:
    try:
        fetch_agent_card_sync(url)
        return True
    except Exception:
        return False


async def check_health(url: str) -> bool:
    try:
        await fetch_agent_card(url)
        return True
    except Exception:
        return False
