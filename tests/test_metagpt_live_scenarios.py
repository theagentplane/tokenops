"""TDD tests for MetaGPT live scenarios and adapter structure."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from benchmarking.metagpt.configs import (
    tokenops_config_for_run,
    tokenops_config_model_routing,
    tokenops_config_steering,
)
from benchmarking.metagpt.evaluate import evaluate_ab, policies_present
from benchmarking.metagpt.scenario_expectations import EXPECTATIONS
from benchmarking.metagpt.scenarios_live import (
    ALL_SUITE,
    CAP_SUITE,
    FAIR_SUITE,
    SCENARIOS,
    SHOWCASE_SUITE,
    TRAP_SUITE,
    get_scenario,
)
from benchmarking.metagpt.scenario_expectations import get_expectation

VENDOR_ROOT = Path(__file__).resolve().parents[1] / "benchmarking/metagpt/vendor"


def _metagpt_importable() -> bool:
    return (VENDOR_ROOT / "metagpt").exists() and importlib.util.find_spec("metagpt") is not None


def test_every_scenario_has_expectation():
    for sid in SCENARIOS:
        assert sid in EXPECTATIONS, f"missing expectation for {sid}"


def test_suites_reference_known_scenarios():
    for sid in (*FAIR_SUITE, *TRAP_SUITE, *CAP_SUITE, *SHOWCASE_SUITE, *ALL_SUITE):
        get_scenario(sid)
        get_expectation(sid)


def test_steering_config_soft_steer_no_pre_call_worst_case():
    cfg = tokenops_config_steering(limit_micros=50_000)
    missing = policies_present(cfg, ("progress_guard", "tool_fix", "cost_guard"))
    assert missing == []
    assert "pre_call_worst_case" not in cfg["policies"]
    assert cfg["policies"]["progress_guard"]["max_corrections"] >= 20


def test_routing_config_includes_cost_guard_downgrade():
    cfg = tokenops_config_model_routing(limit_micros=45_000, downgrade_to="gpt-4o-mini")
    cg = cfg["policies"]["cost_guard"]
    assert cg["mode"] == "downgrade"
    assert cg["downgrade_to"] == "gpt-4o-mini"


def test_tokenops_config_for_run_presets():
    steer = tokenops_config_for_run(limit_micros=60_000, preset="steering")
    route = tokenops_config_for_run(limit_micros=45_000, preset="model_routing")
    guard = tokenops_config_for_run(limit_micros=40_000, preset="cost_guard")
    assert "progress_guard" in steer["policies"]
    assert route["policies"]["cost_guard"]["mode"] == "downgrade"
    assert guard["policies"]["cost_guard"]["threshold"] == 0.75


def test_evaluate_ab_aspirational_when_tokenops_does_not_beat_yet():
    from benchmarking.common.harness import RunOutcome

    ev = evaluate_ab(
        "pricing_verify_trap",
        ungoverned=RunOutcome("pricing_verify_trap", True, 50_000, 6),
        tokenops=RunOutcome("pricing_verify_trap", True, 52_000, 4),
        tokenops_metrics=None,
        limit_usd=0.10,
    )
    assert ev.passed
    assert any("spend" in f for f in ev.aspirational_failures)


def test_evaluate_ab_structural_failure_on_missing_success():
    from benchmarking.common.harness import RunOutcome

    ev = evaluate_ab(
        "saas_baseline",
        ungoverned=RunOutcome("saas_baseline", False, 0, 0, halt_reason="err"),
        tokenops=RunOutcome("saas_baseline", True, 10_000, 2),
        tokenops_metrics=None,
        limit_usd=0.50,
    )
    assert ev.passed


@pytest.mark.skipif(not _metagpt_importable(), reason="metagpt not installed")
def test_install_idempotent():
    from benchmarking.metagpt.integration import install, uninstall

    install()
    install()
    uninstall()


@pytest.mark.skipif(not _metagpt_importable(), reason="metagpt not installed")
@pytest.mark.skipif(not __import__("os").getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")
def test_live_baseline_smoke():
    """Live smoke — run: OPENAI_API_KEY=... pytest tests/test_metagpt_live_scenarios.py -k live_baseline"""
    import asyncio

    from benchmarking.common.harness import BenchmarkMode
    from benchmarking.metagpt.bench_role import make_bench_role
    from benchmarking.metagpt.integration import install, run_governed
    from benchmarking.metagpt.scenarios_live import get_scenario, governance_preset_for

    sc = get_scenario("saas_baseline")
    install()

    async def _run():
        role = make_bench_role(max_react_loop=sc.default_max_react_loop)
        return await run_governed(
            role,
            sc.task,
            mode=BenchmarkMode.TOKENOPS,
            limit_micros=int(sc.default_limit_usd * 1_000_000),
            live_pricing=True,
            governance_preset=governance_preset_for(sc),
        )

    result = asyncio.run(_run())
    assert result.metrics is not None
