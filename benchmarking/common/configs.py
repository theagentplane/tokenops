"""Governance configs for live browser-use runs."""

from __future__ import annotations

from typing import Any


def circuit_breaker_config(*, limit_micros: int) -> dict[str, Any]:
    return {
        "budgets": [
            {"id": "run_llm_cap", "limit_micros": limit_micros, "dimension": "run"},
        ],
        "policies": {
            "cost_budget": {"budget": "run_llm_cap"},
            "pre_call_worst_case": {"budget": "run_llm_cap", "default_max_output": 64},
        },
    }


def tokenops_config(*, limit_micros: int) -> dict[str, Any]:
    return {
        "budgets": [
            {"id": "run_llm_cap", "limit_micros": limit_micros, "dimension": "run"},
        ],
        "policies": {
            "cost_budget": {"budget": "run_llm_cap"},
            # cost_budget is the backstop; pre_call_worst_case blocks late-step completion on
            # browser-use when remaining budget is tight but the agent already has an answer.
            "progress_guard": {"window": 6, "repeats": 2, "max_corrections": 50},
            # tool_fix registry is research-agent shaped; browser-use actions differ — skip for live bench
            "tool_output_cap": {"cap_tokens": 8000},
            "output_runaway": {"repeats": 12, "domination": 0.9, "max_retries": 2},
            "context_compaction": {"ctx_max": 100_000, "has_hook": True},
            "cost_guard": {"budget": "run_llm_cap", "threshold": 0.8, "mode": "minimize"},
        },
    }


def tokenops_config_for_run(*, limit_micros: int, max_steps: int) -> dict[str, Any]:
    """TokenOps stack for live runs — browser-use ``max_steps`` is the step limit."""
    del max_steps  # agent.run enforces; governor step_cap counts boundary crossings
    return tokenops_config(limit_micros=limit_micros)


def tokenops_config_metagpt(*, limit_micros: int) -> dict[str, Any]:
    """Backward-compatible alias — default MetaGPT steer preset."""
    from benchmarking.metagpt.configs import tokenops_config_steering

    return tokenops_config_steering(limit_micros=limit_micros)


def tokenops_config_metagpt_steering(*, limit_micros: int) -> dict[str, Any]:
    from benchmarking.metagpt.configs import tokenops_config_steering

    return tokenops_config_steering(limit_micros=limit_micros)


def tokenops_config_metagpt_routing(
    *,
    limit_micros: int,
    downgrade_to: str = "gpt-4o-mini",
    threshold: float = 0.55,
) -> dict[str, Any]:
    del threshold
    from benchmarking.metagpt.configs import tokenops_config_model_routing

    return tokenops_config_model_routing(limit_micros=limit_micros, downgrade_to=downgrade_to)
