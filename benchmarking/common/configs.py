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
            "pre_call_worst_case": {"budget": "run_llm_cap", "default_max_output": 64},
            "progress_guard": {"window": 6, "repeats": 2, "max_corrections": 4},
            "tool_fix": {"registry": ["search", "click", "navigate", "extract"], "k": 3},
            "tool_output_cap": {"cap_tokens": 8000},
            "output_runaway": {"repeats": 12, "domination": 0.9, "max_retries": 2},
            "context_compaction": {"ctx_max": 100_000, "has_hook": True},
            "cost_guard": {"budget": "run_llm_cap", "threshold": 0.8, "mode": "minimize"},
            "step_cap": {"max_steps": 25},
        },
    }
