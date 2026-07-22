from __future__ import annotations

import os

from examples.a2a import messages
from examples.a2a.server import fetch_agent_card, fetch_agent_card_sync, post_task, post_task_sync
from examples.agents.types import Finding, RunResult, StepEvent, TokenUsage
from examples.a2a.messages import parse_findings, parse_token_usage, summarize_request, parse_steps
from tokenops.control.context import PARENT_SPAN_ID_HEADER, RUN_ID_HEADER
from tokenops.control.models import GovernanceMode


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
    result, _meta = submit_task_sync_with_meta(
        research_url,
        task,
        corpus_profile=corpus_profile,
        intent=intent,
        user_dims=user_dims,
    )
    return result


def submit_task_sync_with_meta(
    research_url: str,
    task: str,
    *,
    corpus_profile: str = "healthy",
    intent: str = "",
    user_dims: dict[str, str] | None = None,
    governance_mode: GovernanceMode = GovernanceMode.ENFORCE,
) -> tuple[RunResult, dict[str, object]]:
    """POST a task to the research entry agent (UI path).

    Research registers the run when ``X-TokenOps-Run-Id`` is absent — clients should
    not call ``/v1/runs`` themselves for the default Chat / bench flow.
    """
    if not (os.environ.get("TOKENOPS_URL") or "").strip() and os.environ.get("TOKENOPS_EMBEDDED") != "1":
        os.environ.setdefault("TOKENOPS_EMBEDDED", "1")
    payload = messages.task_request(task=task, bench={"corpus_profile": corpus_profile}, intent=intent)
    if user_dims:
        payload["user_dims"] = user_dims
    payload["mode"] = (
        governance_mode.value if isinstance(governance_mode, GovernanceMode) else governance_mode
    )
    data = post_task_sync(research_url, payload, headers=None)
    result = _parse_run_result(data)
    meta: dict[str, object] = {
        "status": data.get("status"),
        "halt_reason": data.get("halt_reason"),
        "cost_micros": int(data.get("cost_micros", 0)),
        "governance_events": data.get("governance_events") or [],
        "run_id": data.get("run_id"),
    }
    return result, meta


async def submit_task(
    research_url: str,
    task: str,
    *,
    corpus_profile: str = "healthy",
    intent: str = "",
    user_dims: dict[str, str] | None = None,
) -> RunResult:
    if not (os.environ.get("TOKENOPS_URL") or "").strip() and os.environ.get("TOKENOPS_EMBEDDED") != "1":
        os.environ.setdefault("TOKENOPS_EMBEDDED", "1")
    payload = messages.task_request(task=task, bench={"corpus_profile": corpus_profile}, intent=intent)
    if user_dims:
        payload["user_dims"] = user_dims
    data = await post_task(research_url, payload, headers=None)
    return _parse_run_result(data)


async def delegate_summarize(
    summarize_url: str,
    task: str,
    findings: list[Finding],
    *,
    run_id: str | None = None,
    parent_span_id: str | None = None,
) -> tuple[str, TokenUsage, list[StepEvent], int]:
    """Delegate to summarize. Headers come from ambient context when omitted."""
    payload = summarize_request(task=task, findings=findings)
    headers: dict[str, str] = {}
    if run_id:
        headers[RUN_ID_HEADER] = run_id
    if parent_span_id:
        headers[PARENT_SPAN_ID_HEADER] = parent_span_id
    data = await post_task(summarize_url, payload, headers=headers or None)
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
