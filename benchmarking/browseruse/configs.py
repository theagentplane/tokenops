"""Browser-use governance presets — keep MetaGPT configs in benchmarking/common untouched."""

from __future__ import annotations

from typing import Any, Callable

# Actions browser-use may emit; used as the allow-list for tool_fix in the default steer preset.
BROWSERUSE_ACTION_REGISTRY: list[str] = [
    "navigate",
    "done",
    "go_back",
    "wait",
    "click",
    "input",
    "scroll",
    "search",
    "search_page",
    "find_elements",
    "evaluate",
    "extract",
    "send_keys",
    "upload_file",
    "switch",
    "close",
]

# Narrow allow-list: any click / search_page / find_elements trips tool_fix INJECT.
TOOL_FIX_STRICT_REGISTRY: list[str] = ["navigate", "done", "evaluate"]


def _base_budget(limit_micros: int) -> dict[str, Any]:
    return {
        "budgets": [
            {"id": "run_llm_cap", "limit_micros": limit_micros, "dimension": "run"},
        ],
    }


def tokenops_config_steering(*, limit_micros: int, max_steps: int = 100) -> dict[str, Any]:
    """Full steer stack for live browser-use A/B."""
    del max_steps
    return {
        **_base_budget(limit_micros),
        "policies": {
            "cost_budget": {"budget": "run_llm_cap"},
            "progress_guard": {"window": 5, "repeats": 2, "max_corrections": 20},
            "tool_fix": {"registry": list(BROWSERUSE_ACTION_REGISTRY), "k": 2},
            "tool_output_cap": {"cap_tokens": 8000},
            "output_runaway": {"repeats": 12, "domination": 0.9, "max_retries": 2},
            "context_compaction": {"ctx_max": 100_000, "has_hook": True},
            "cost_guard": {"budget": "run_llm_cap", "threshold": 0.8, "mode": "minimize"},
        },
    }


def tokenops_config_cost_guard(*, limit_micros: int, max_steps: int = 100) -> dict[str, Any]:
    """Emphasize cost_guard minimize inject near 80% spend."""
    del max_steps
    cfg = tokenops_config_steering(limit_micros=limit_micros)
    cfg["policies"]["progress_guard"] = {"window": 8, "repeats": 3, "max_corrections": 6}
    cfg["policies"]["cost_guard"] = {
        "budget": "run_llm_cap",
        "threshold": 0.75,
        "mode": "minimize",
    }
    return cfg


def tokenops_config_tool_fix(*, limit_micros: int, max_steps: int = 100) -> dict[str, Any]:
    """Trip tool_fix when the agent uses click/search_page outside the narrow registry."""
    del max_steps
    cfg = tokenops_config_steering(limit_micros=limit_micros)
    cfg["policies"]["tool_fix"] = {"registry": list(TOOL_FIX_STRICT_REGISTRY), "k": 2}
    cfg["policies"]["progress_guard"] = {"window": 8, "repeats": 3, "max_corrections": 4}
    return cfg


def tokenops_config_tool_output_cap(*, limit_micros: int, max_steps: int = 100) -> dict[str, Any]:
    """Lower cap so evaluate/extract page dumps trigger offload quickly."""
    del max_steps
    cfg = tokenops_config_steering(limit_micros=limit_micros)
    cfg["policies"]["tool_output_cap"] = {"cap_tokens": 3500}
    return cfg


PRESETS: dict[str, Callable[..., dict[str, Any]]] = {
    "steering": tokenops_config_steering,
    "cost_guard": tokenops_config_cost_guard,
    "tool_fix": tokenops_config_tool_fix,
    "tool_output_cap": tokenops_config_tool_output_cap,
}


def tokenops_config_for_run(
    *,
    limit_micros: int,
    max_steps: int = 100,
    preset: str = "steering",
) -> dict[str, Any]:
    fn = PRESETS.get(preset, tokenops_config_steering)
    return fn(limit_micros=limit_micros, max_steps=max_steps)
