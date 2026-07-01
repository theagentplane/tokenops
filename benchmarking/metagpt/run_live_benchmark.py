#!/usr/bin/env python3
"""Live MetaGPT A/B: vanilla vs TokenOps (aligned with browser-use suites)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from tokenops.env import load_env  # noqa: E402

from benchmarking.common.harness import BenchmarkMode, CompareMode, RunOutcome  # noqa: E402
from benchmarking.metagpt.bootstrap import bootstrap_metagpt_from_env  # noqa: E402
from benchmarking.metagpt.bench_role import make_bench_role  # noqa: E402
from benchmarking.metagpt.evaluate import evaluate_ab  # noqa: E402
from benchmarking.metagpt.integration import (  # noqa: E402
    GovernedRunResult,
    install,
    run_governed,
    run_ungoverned,
)
from benchmarking.metagpt.scenarios_live import (  # noqa: E402
    POLICY_SUITE,
    STEER_SUITE,
    STRESS_SUITE,
    LiveScenario,
    get_scenario,
)

COOLDOWN_BETWEEN_ARMS_SEC = 90


@dataclass
class LiveTrial:
    trial: int
    mode: CompareMode
    outcome: RunOutcome
    policy_signals: tuple[str, ...] = ()
    models_used: tuple[str, ...] = ()
    within_budget: bool = False
    success_within_budget: bool = False


@dataclass
class LiveModeSummary:
    mode: CompareMode
    trials: list[LiveTrial] = field(default_factory=list)

    def _spends(self) -> list[float]:
        return [t.outcome.spend_micros / 1_000_000 for t in self.trials]

    @property
    def avg_spend_usd(self) -> float:
        return mean(self._spends()) if self.trials else 0.0

    @property
    def median_spend_usd(self) -> float:
        return float(median(self._spends())) if self.trials else 0.0

    @property
    def successes(self) -> int:
        return sum(1 for t in self.trials if t.outcome.success)

    @property
    def success_within_budget_count(self) -> int:
        return sum(1 for t in self.trials if t.success_within_budget)


@dataclass
class ScenarioResult:
    scenario: LiveScenario
    ungoverned: LiveModeSummary
    tokenops: LiveModeSummary
    evaluation: dict | None = None


def _require_metagpt() -> None:
    bootstrap_metagpt_from_env()
    try:
        import metagpt  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "MetaGPT not installed. Run: pip install -e benchmarking/metagpt/vendor"
        ) from exc


def _trial_from_result(
    result: GovernedRunResult,
    *,
    mode: CompareMode,
    scenario_id: str,
    limit_micros: int,
) -> LiveTrial:
    m = result.metrics
    if m is None:
        return LiveTrial(
            trial=0,
            mode=mode,
            outcome=RunOutcome(
                scenario_id=scenario_id,
                success=False,
                spend_micros=0,
                steps=0,
                halt_reason=result.error or "no metrics",
            ),
        )

    spend = m.spend_micros
    if mode is CompareMode.UNGOVERNED:
        success = result.success
        halted = False
    else:
        halted = m.halted
        success = (result.success and not halted) or (
            halted and result.success and (m.run_done or m.react_rounds > 0)
        )

    within_budget = spend <= limit_micros and (
        not halted or (success and m.run_done)
    )
    return LiveTrial(
        trial=0,
        mode=mode,
        outcome=RunOutcome(
            scenario_id=scenario_id,
            success=success,
            spend_micros=spend,
            steps=m.react_rounds,
            halt_reason=m.halt_reason or result.error,
        ),
        policy_signals=m.policy_signals,
        models_used=m.models_used,
        within_budget=within_budget,
        success_within_budget=success and within_budget,
    )


async def _run_trial(
    mode: CompareMode,
    *,
    scenario: LiveScenario,
    limit_micros: int,
    trial: int,
) -> GovernedRunResult:
    _require_metagpt()
    role = make_bench_role(
        max_react_loop=scenario.default_max_react_loop,
        model=scenario.primary_model,
    )
    print(
        f"\n--- {scenario.id} | trial {trial} | {mode.value} ({scenario.primary_model}) ---",
        flush=True,
    )

    if mode is CompareMode.UNGOVERNED:
        return await run_ungoverned(role, scenario.task)

    install()
    return await run_governed(
        role,
        scenario.task,
        mode=BenchmarkMode.TOKENOPS,
        limit_micros=limit_micros,
        live_pricing=True,
        governance_preset=scenario.governance_preset,
        downgrade_to=scenario.downgrade_to,
        max_react_loop=scenario.default_max_react_loop,
    )


def _pct_reduction(baseline: float, improved: float) -> float:
    if baseline <= 0:
        return 0.0
    return round(100.0 * (baseline - improved) / baseline, 1)


def _format_summary(
    base: LiveModeSummary,
    governed: LiveModeSummary,
    *,
    scenario: LiveScenario,
    limit_usd: float,
    trials: int,
    evaluation: dict | None,
) -> str:
    spend_red = _pct_reduction(base.avg_spend_usd, governed.avg_spend_usd)
    lines = [
        f"=== {scenario.id}: ungoverned vs TokenOps ({trials} trial(s)) ===",
        f"    {scenario.description}",
        f"    preset: {scenario.governance_preset}  cap: ${limit_usd:.3f}  "
        f"model: {scenario.primary_model}  max_react: {scenario.default_max_react_loop}",
        "",
        "Without TokenOps",
        f"   successes: {base.successes}/{trials}  success within cap: {base.success_within_budget_count}/{trials}",
        f"   avg spend: ${base.avg_spend_usd:.4f}  median ${base.median_spend_usd:.4f}",
        "",
        "With TokenOps",
        f"   successes: {governed.successes}/{trials} (+{governed.successes - base.successes})",
        f"   success within cap: {governed.success_within_budget_count}/{trials} "
        f"(+{governed.success_within_budget_count - base.success_within_budget_count})",
        f"   avg spend: ${governed.avg_spend_usd:.4f} ({spend_red:+.1f}% vs ungoverned)",
        "",
        "Per-trial:",
    ]
    for i in range(trials):
        u = base.trials[i] if i < len(base.trials) else None
        g = governed.trials[i] if i < len(governed.trials) else None
        if u and g:
            sig = f" signals={list(g.policy_signals)}" if g.policy_signals else ""
            models = f" models={list(g.models_used)}" if g.models_used else ""
            lines.append(
                f"  trial {i + 1}:  vanilla {'ok' if u.outcome.success else 'FAIL':4} "
                f"${u.outcome.spend_micros / 1_000_000:.4f} {u.outcome.steps}r  |  "
                f"TokenOps {'ok' if g.outcome.success else 'FAIL':4} "
                f"${g.outcome.spend_micros / 1_000_000:.4f} {g.outcome.steps}r{sig}{models}"
            )
    if evaluation:
        lines.append("")
        passed = evaluation.get("passed")
        aspirational = evaluation.get("aspirational_failures", [])
        lines.append(
            f"TDD: {'PASS' if passed and not aspirational else 'STRUCTURAL PASS'}"
            + (" (aspirational spend/signal wins pending)" if aspirational else "")
        )
        for f in evaluation.get("failures", []):
            lines.append(f"  fail: {f}")
        for f in aspirational:
            lines.append(f"  aspirational: {f}")
    return "\n".join(lines)


async def _run_scenario_ab(
    scenario: LiveScenario,
    *,
    limit_usd: float,
    trials: int,
    mode_only: str | None,
    cooldown_sec: int,
) -> ScenarioResult:
    limit_micros = int(limit_usd * 1_000_000)
    summaries = {
        CompareMode.UNGOVERNED: LiveModeSummary(mode=CompareMode.UNGOVERNED),
        CompareMode.TOKENOPS: LiveModeSummary(mode=CompareMode.TOKENOPS),
    }
    order = [CompareMode(mode_only)] if mode_only else [CompareMode.UNGOVERNED, CompareMode.TOKENOPS]
    last_tokenops_metrics = None

    for trial in range(1, trials + 1):
        for i, mode in enumerate(order):
            if i > 0 and cooldown_sec > 0:
                print(f"\n… cooldown {cooldown_sec}s before {mode.value} …", flush=True)
                await asyncio.sleep(cooldown_sec)
            try:
                res = await _run_trial(mode, scenario=scenario, limit_micros=limit_micros, trial=trial)
                live = _trial_from_result(
                    res, mode=mode, scenario_id=scenario.id, limit_micros=limit_micros,
                )
                live.trial = trial
                summaries[mode].trials.append(live)
                if mode is CompareMode.TOKENOPS:
                    last_tokenops_metrics = res.metrics
                m = res.metrics
                if m:
                    cap = limit_micros / 1_000_000
                    budget_note = (
                        f"ref cap ${cap:.3f}"
                        if mode is CompareMode.UNGOVERNED
                        else f"cap ${cap:.3f} ({'under' if m.spend_micros <= limit_micros and not m.halted else 'over/halted'})"
                    )
                    print(
                        f"  spend ${m.spend_micros / 1_000_000:.4f} ({budget_note})  "
                        f"rounds {m.react_rounds}  success={res.success}  "
                        f"halted={m.halted}  signals={list(m.policy_signals)}",
                        flush=True,
                    )
                    if m.halt_reason or res.error:
                        print(f"  halt/error: {m.halt_reason or res.error}", flush=True)
            except Exception as exc:
                print(f"  run failed: {exc}", file=sys.stderr)
                summaries[mode].trials.append(
                    LiveTrial(
                        trial=trial,
                        mode=mode,
                        outcome=RunOutcome(
                            scenario_id=scenario.id,
                            success=False,
                            spend_micros=0,
                            steps=0,
                            halt_reason=str(exc),
                        ),
                    )
                )

    eval_dict = None
    if not mode_only and summaries[CompareMode.UNGOVERNED].trials and summaries[CompareMode.TOKENOPS].trials:
        ev = evaluate_ab(
            scenario.id,
            ungoverned=summaries[CompareMode.UNGOVERNED].trials[-1].outcome,
            tokenops=summaries[CompareMode.TOKENOPS].trials[-1].outcome,
            tokenops_metrics=last_tokenops_metrics,
            limit_usd=limit_usd,
        )
        eval_dict = ev.to_dict()

    return ScenarioResult(
        scenario=scenario,
        ungoverned=summaries[CompareMode.UNGOVERNED],
        tokenops=summaries[CompareMode.TOKENOPS],
        evaluation=eval_dict,
    )


async def async_main() -> int:
    load_env()
    bootstrap_metagpt_from_env()
    scenario_names = list(dict.fromkeys([*POLICY_SUITE, *STRESS_SUITE, *STEER_SUITE]))
    parser = argparse.ArgumentParser(description="Live MetaGPT: vanilla vs TokenOps")
    parser.add_argument(
        "--scenario",
        choices=[*scenario_names, "all", "policy_suite", "stress_suite", "steer_suite", "showcase_suite"],
        default="policy_suite",
        help="Task preset (default: policy_suite; steer_suite = cost_guard/model_routing)",
    )
    parser.add_argument("--limit-usd", type=float, default=None)
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--mode-only", choices=["ungoverned", "tokenops"], default=None)
    parser.add_argument("--cooldown-sec", type=int, default=COOLDOWN_BETWEEN_ARMS_SEC)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    if args.scenario == "all":
        ids = scenario_names
    elif args.scenario == "policy_suite":
        ids = list(POLICY_SUITE)
    elif args.scenario == "stress_suite":
        ids = list(STRESS_SUITE)
    elif args.scenario == "steer_suite":
        ids = list(STEER_SUITE)
    elif args.scenario == "showcase_suite":
        ids = list(STRESS_SUITE + STEER_SUITE)
    else:
        ids = [args.scenario]

    results: list[ScenarioResult] = []
    for sid in ids:
        sc = get_scenario(sid)
        limit_usd = args.limit_usd if args.limit_usd is not None else sc.default_limit_usd
        results.append(
            await _run_scenario_ab(
                sc,
                limit_usd=limit_usd,
                trials=args.trials,
                mode_only=args.mode_only,
                cooldown_sec=args.cooldown_sec if not args.mode_only else 0,
            )
        )

    if args.as_json:
        print(json.dumps([
            {
                "scenario": r.scenario.id,
                "preset": r.scenario.governance_preset,
                "evaluation": r.evaluation,
                "ungoverned_avg_spend": round(r.ungoverned.avg_spend_usd, 6),
                "tokenops_avg_spend": round(r.tokenops.avg_spend_usd, 6),
            }
            for r in results
        ], indent=2))
    else:
        for r in results:
            limit = args.limit_usd or r.scenario.default_limit_usd
            print("\n" + _format_summary(
                r.ungoverned,
                r.tokenops,
                scenario=r.scenario,
                limit_usd=limit,
                trials=args.trials,
                evaluation=r.evaluation,
            ))
    return 0


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
