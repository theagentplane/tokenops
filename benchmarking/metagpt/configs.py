"""MetaGPT governance presets — mirror browser-use steer stack (soft INJECT over hard HALT)."""

from __future__ import annotations

from typing import Any, Callable

METAGPT_ACTION_REGISTRY: list[str] = ["Research"]


def _base_budget(limit_micros: int) -> dict[str, Any]:
    return {
        "budgets": [
            {"id": "run_llm_cap", "limit_micros": limit_micros, "dimension": "run"},
        ],
    }


def tokenops_config_steering(*, limit_micros: int, max_react_loop: int = 100) -> dict[str, Any]:
    """Default steer stack — progress_guard + cost_guard minimize; no pre_call_worst_case."""
    del max_react_loop
    return {
        **_base_budget(limit_micros),
        "policies": {
            "cost_budget": {"budget": "run_llm_cap"},
            "progress_guard": {"window": 5, "repeats": 2, "max_corrections": 20},
            "tool_fix": {"registry": list(METAGPT_ACTION_REGISTRY), "k": 2},
            "tool_output_cap": {"cap_tokens": 6000},
            "output_runaway": {"repeats": 10, "domination": 0.88, "max_retries": 2},
            "context_compaction": {"ctx_max": 80_000, "has_hook": True},
            "cost_guard": {"budget": "run_llm_cap", "threshold": 0.8, "mode": "minimize"},
        },
    }


def tokenops_config_cost_guard(*, limit_micros: int, max_react_loop: int = 100) -> dict[str, Any]:
    """Emphasize cost_guard minimize inject near ~75% spend."""
    del max_react_loop
    cfg = tokenops_config_steering(limit_micros=limit_micros)
    cfg["policies"]["progress_guard"] = {"window": 8, "repeats": 3, "max_corrections": 12}
    cfg["policies"]["cost_guard"] = {
        "budget": "run_llm_cap",
        "threshold": 0.75,
        "mode": "minimize",
    }
    return cfg


def tokenops_config_model_routing(
    *,
    limit_micros: int,
    max_react_loop: int = 100,
    downgrade_to: str = "gpt-4o-mini",
) -> dict[str, Any]:
    """Model routing via cost_guard downgrade (soft mutate, not halt)."""
    del max_react_loop
    cfg = tokenops_config_steering(limit_micros=limit_micros)
    cfg["policies"]["cost_guard"] = {
        "budget": "run_llm_cap",
        "threshold": 0.55,
        "mode": "downgrade",
        "downgrade_to": downgrade_to,
    }
    return cfg


PRESETS: dict[str, Callable[..., dict[str, Any]]] = {
    "steering": tokenops_config_steering,
    "cost_guard": tokenops_config_cost_guard,
    "model_routing": tokenops_config_model_routing,
}


def tokenops_config_for_run(
    *,
    limit_micros: int,
    max_react_loop: int = 100,
    preset: str = "steering",
    downgrade_to: str = "gpt-4o-mini",
) -> dict[str, Any]:
    if preset == "model_routing":
        return tokenops_config_model_routing(
            limit_micros=limit_micros,
            max_react_loop=max_react_loop,
            downgrade_to=downgrade_to,
        )
    fn = PRESETS.get(preset, tokenops_config_steering)
    return fn(limit_micros=limit_micros, max_react_loop=max_react_loop)
