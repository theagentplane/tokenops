#!/usr/bin/env python3
"""Live browser-use A/B: vanilla vs TokenOps."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from tokenops.env import load_env  # noqa: E402

from benchmarking.browseruse.integration import (  # noqa: E402
    GovernedRunResult,
    install,
    run_governed,
    run_ungoverned,
)
from benchmarking.browseruse.scenarios_live import (  # noqa: E402
    ALL_SUITE,
    SUITE_BY_NAME,
    LiveScenario,
    get_scenario,
)
from benchmarking.common.harness import BenchmarkMode, CompareMode, RunOutcome  # noqa: E402
from benchmarking.common.trial import (  # noqa: E402
    TrialStatus,
    classify_trial,
    classify_win,
    showcase_pass,
)

LIVE_DEFAULT_LIMIT_USD = 0.50
COOLDOWN_BETWEEN_ARMS_SEC = 90


@dataclass
class LiveTrial:
    trial: int
    mode: CompareMode
    outcome: RunOutcome
    total_tokens: int = 0
    browser_cost_usd: float = 0.0
    within_budget: bool = False
    success_within_budget: bool = False
    status: TrialStatus = TrialStatus.FAILED
    halted: bool = False


@dataclass
class LiveModeSummary:
    mode: CompareMode
    trials: list[LiveTrial] = field(default_factory=list)

    def _scored(self) -> list[LiveTrial]:
        return [t for t in self.trials if t.status is not TrialStatus.INFRA]

    def _spends(self) -> list[float]:
        return [t.outcome.spend_micros / 1_000_000 for t in self._scored()]

    def _tokens(self) -> list[int]:
        return [t.total_tokens for t in self._scored()]

    @property
    def total_trials(self) -> int:
        return len(self.trials)

    @property
    def scored_trials(self) -> int:
        return len(self._scored())

    @property
    def infra_trials(self) -> int:
        return sum(1 for t in self.trials if t.status is TrialStatus.INFRA)

    @property
    def avg_spend_usd(self) -> float:
        return mean(self._spends()) if self._scored() else 0.0

    @property
    def median_spend_usd(self) -> float:
        return float(median(self._spends())) if self._scored() else 0.0

    @property
    def avg_tokens(self) -> float:
        return mean(self._tokens()) if self._scored() else 0.0

    @property
    def median_tokens(self) -> float:
        return float(median(self._tokens())) if self._scored() else 0.0

    @property
    def successes(self) -> int:
        return sum(1 for t in self._scored() if t.outcome.success)

    @property
    def success_within_budget_count(self) -> int:
        return sum(1 for t in self._scored() if t.success_within_budget)

    @property
    def avg_steps(self) -> float:
        scored = self._scored()
        return mean([t.outcome.steps for t in scored]) if scored else 0.0


@dataclass
class ScenarioResult:
    scenario: LiveScenario
    ungoverned: LiveModeSummary
    tokenops: LiveModeSummary


def _pick_llm():
    from browser_use import ChatBrowserUse, ChatOpenAI

    if os.getenv("BROWSER_USE_API_KEY"):
        return ChatBrowserUse(), "ChatBrowserUse"
    if os.getenv("OPENAI_API_KEY"):
        return ChatOpenAI(model="gpt-4o-mini"), "ChatOpenAI(gpt-4o-mini)"
    return None, ""


def _make_agent(task: str):
    from browser_use import Agent, Browser

    llm, name = _pick_llm()
    if llm is None:
        raise RuntimeError("Set BROWSER_USE_API_KEY or OPENAI_API_KEY in .env")
    browser = Browser(headless=True)
    agent = Agent(task=task, llm=llm, browser=browser, calculate_cost=True)
    return agent, name


def _usage_from_history(history) -> dict[str, int | float]:
    usage = getattr(history, "usage", None) if history is not None else None
    if usage is None:
        return {}
    return {
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
        "browser_cost_usd": float(getattr(usage, "total_cost", 0.0) or 0.0),
    }


def _trial_from_result(
    result: GovernedRunResult,
    *,
    mode: CompareMode,
    scenario_id: str,
    limit_micros: int,
) -> LiveTrial:
    m = result.metrics
    usage = _usage_from_history(result.history)
    browser_spend = int(round(usage.get("browser_cost_usd", 0.0) * 1_000_000))
    if m is None:
        outcome = RunOutcome(
            scenario_id=scenario_id,
            success=False,
            spend_micros=0,
            steps=0,
            halt_reason=result.error or "no metrics",
        )
        status = classify_trial(
            success=False,
            spend_micros=0,
            steps=0,
            halt_reason=outcome.halt_reason,
            halted=False,
        )
        return LiveTrial(trial=0, mode=mode, outcome=outcome, status=status)

    if mode is CompareMode.UNGOVERNED:
        spend = browser_spend or m.spend_micros
        success = bool(m.agent_success)
        halted = False
    else:
        spend = browser_spend or m.spend_micros
        halted = m.halted
        success = (result.success and not halted) or (
            halted
            and bool(m.agent_success)
            and (m.agent_done or bool(usage.get("browser_cost_usd")))
        )

    within_budget = spend <= limit_micros and (
        not halted or (success and m.agent_done)
    )
    outcome = RunOutcome(
        scenario_id=scenario_id,
        success=success,
        spend_micros=spend,
        steps=m.agent_steps,
        halt_reason=m.halt_reason or result.error,
    )
    status = classify_trial(
        success=success,
        spend_micros=spend,
        steps=m.agent_steps,
        halt_reason=outcome.halt_reason,
        halted=halted,
    )
    return LiveTrial(
        trial=0,
        mode=mode,
        outcome=outcome,
        total_tokens=int(usage.get("total_tokens", 0)),
        browser_cost_usd=float(usage.get("browser_cost_usd", 0.0)),
        within_budget=within_budget,
        success_within_budget=success and within_budget,
        status=status,
        halted=halted,
    )


async def _run_trial(
    mode: CompareMode,
    *,
    scenario: LiveScenario,
    limit_micros: int,
    max_steps: int,
    trial: int,
) -> GovernedRunResult:
    agent, llm_name = _make_agent(scenario.task)
    print(
        f"\n--- {scenario.id} | trial {trial} | {mode.value} ({llm_name}) ---",
        flush=True,
    )

    if mode is CompareMode.UNGOVERNED:
        result = await run_ungoverned(agent, max_steps=max_steps)
    else:
        install()
        result = await run_governed(
            agent,
            mode=BenchmarkMode.TOKENOPS,
            limit_micros=limit_micros,
            live_pricing=True,
            max_steps=max_steps,
            governance_preset="steering",
        )

    m = result.metrics
    usage = _usage_from_history(result.history)
    if m:
        cap = limit_micros / 1_000_000
        spend_usd = (
            usage.get("browser_cost_usd", m.spend_micros / 1_000_000)
            if mode is CompareMode.UNGOVERNED
            else (m.spend_micros / 1_000_000) or usage.get("browser_cost_usd", 0.0)
        )
        budget_note = (
            f"ref cap ${cap:.2f}"
            if mode is CompareMode.UNGOVERNED
            else f"cap ${cap:.2f} ({'under' if m.spend_micros <= limit_micros and not m.halted else 'over/halted'})"
        )
        browser_spend = int(round(usage.get("browser_cost_usd", 0.0) * 1_000_000))
        if mode is CompareMode.UNGOVERNED:
            spend = browser_spend or m.spend_micros
            success = bool(m.agent_success)
            halted = False
        else:
            spend = browser_spend or m.spend_micros
            halted = m.halted
            success = (result.success and not halted) or (
                halted
                and bool(m.agent_success)
                and (m.agent_done or bool(usage.get("browser_cost_usd")))
            )
        trial_status = classify_trial(
            success=success,
            spend_micros=spend,
            steps=m.agent_steps,
            halt_reason=m.halt_reason or result.error,
            halted=halted,
        )
        print(
            f"  spend ${spend_usd:.4f} ({budget_note})  steps {m.agent_steps}  "
            f"success={m.agent_success}  halted={halted}  status={trial_status.value}",
            flush=True,
        )
        if usage.get("total_tokens"):
            print(
                f"  tokens {usage['total_tokens']:,}  browser_cost ${usage.get('browser_cost_usd', 0):.4f}",
                flush=True,
            )
        if m.halt_reason or result.error:
            print(f"  halt/error: {m.halt_reason or result.error}", flush=True)
    if result.history and result.history.final_result():
        snippet = (result.history.final_result() or "")[:400]
        print(f"  result: {snippet}…", flush=True)
    return result


def _pct_reduction(baseline: float, improved: float) -> float:
    if baseline <= 0:
        return 0.0
    return round(100.0 * (baseline - improved) / baseline, 2)


def _format_summary(
    base: LiveModeSummary,
    governed: LiveModeSummary,
    *,
    scenario: LiveScenario,
    limit_usd: float,
    trials: int,
    suite: str | None = None,
) -> str:
    spend_red = _pct_reduction(base.avg_spend_usd, governed.avg_spend_usd)
    token_red = _pct_reduction(base.avg_tokens, governed.avg_tokens)
    win = classify_win(
        ungoverned_spend=base.avg_spend_usd,
        tokenops_spend=governed.avg_spend_usd,
        ungoverned_steps=base.avg_steps,
        tokenops_steps=governed.avg_steps,
        ungoverned_success_within=base.success_within_budget_count,
        tokenops_success_within=governed.success_within_budget_count,
        trials=trials,
    )
    demo_ok = showcase_pass(
        ungoverned_spend=base.avg_spend_usd,
        tokenops_spend=governed.avg_spend_usd,
        ungoverned_success_within=base.success_within_budget_count,
        tokenops_success_within=governed.success_within_budget_count,
    )
    lines = [
        f"=== {scenario.id}: ungoverned vs TokenOps ({trials} trial(s)) ===",
        f"    suite: {suite or scenario.suite}  |  win: {win}"
        + (f"  |  showcase_pass: {demo_ok}" if suite == "showcase" or scenario.suite == "showcase" else ""),
        f"    {scenario.description}",
        f"    TokenOps cap: ${limit_usd:.2f}  max_steps: {scenario.default_max_steps}",
        "",
        "Without TokenOps",
        f"   scored: {base.scored_trials}/{base.total_trials}  infra dropped: {base.infra_trials}",
        f"   successes: {base.successes}/{base.scored_trials or trials}  "
        f"within cap: {base.success_within_budget_count}/{base.scored_trials or trials}",
        f"   avg spend: ${base.avg_spend_usd:.4f}  median ${base.median_spend_usd:.4f}",
        f"   avg steps: {base.avg_steps:.1f}  avg tokens: {base.avg_tokens:,.0f}",
        "",
        "With TokenOps",
        f"   scored: {governed.scored_trials}/{governed.total_trials}  infra dropped: {governed.infra_trials}",
        f"   successes: {governed.successes}/{governed.scored_trials or trials}  "
        f"within cap: {governed.success_within_budget_count}/{governed.scored_trials or trials}",
        f"   avg spend: ${governed.avg_spend_usd:.4f} ({spend_red:+.1f}% vs ungoverned)",
        f"   avg steps: {governed.avg_steps:.1f}  avg tokens: {governed.avg_tokens:,.0f} ({token_red:+.1f}%)",
        "",
        "Per-trial:",
    ]
    for i in range(trials):
        u = base.trials[i] if i < len(base.trials) else None
        g = governed.trials[i] if i < len(governed.trials) else None
        if u and g:
            lines.append(
                f"  trial {i + 1}:  vanilla {u.status.value:6} "
                f"{'ok' if u.outcome.success else 'FAIL':4} "
                f"${u.outcome.spend_micros / 1_000_000:.4f} {u.total_tokens:,} tok {u.outcome.steps} steps  |  "
                f"TokenOps {g.status.value:6} "
                f"{'ok' if g.outcome.success else 'FAIL':4} "
                f"${g.outcome.spend_micros / 1_000_000:.4f} {g.total_tokens:,} tok {g.outcome.steps} steps"
            )
    return "\n".join(lines)


async def _run_single_trial(
    trial: int,
    *,
    order: list[CompareMode],
    scenario: LiveScenario,
    limit_micros: int,
    max_steps: int,
    cooldown_sec: int,
) -> dict[CompareMode, LiveTrial]:
    out: dict[CompareMode, LiveTrial] = {}
    for i, mode in enumerate(order):
        if i > 0 and cooldown_sec > 0:
            print(f"\n… cooldown {cooldown_sec}s before {mode.value} (trial {trial}) …", flush=True)
            await asyncio.sleep(cooldown_sec)
        try:
            res = await _run_trial(
                mode,
                scenario=scenario,
                limit_micros=limit_micros,
                max_steps=max_steps,
                trial=trial,
            )
            live = _trial_from_result(
                res, mode=mode, scenario_id=scenario.id, limit_micros=limit_micros,
            )
            live.trial = trial
            out[mode] = live
        except Exception as exc:
            print(f"  run failed (trial {trial}): {exc}", file=sys.stderr)
            outcome = RunOutcome(
                scenario_id=scenario.id,
                success=False,
                spend_micros=0,
                steps=0,
                halt_reason=str(exc),
            )
            out[mode] = LiveTrial(
                trial=trial,
                mode=mode,
                outcome=outcome,
                status=classify_trial(
                    success=False,
                    spend_micros=0,
                    steps=0,
                    halt_reason=str(exc),
                    halted=False,
                ),
            )
    return out


async def _run_scenario_ab(
    scenario: LiveScenario,
    *,
    limit_usd: float,
    max_steps: int,
    trials: int,
    mode_only: str | None,
    cooldown_sec: int,
    parallel_batch: int = 1,
) -> ScenarioResult:
    limit_micros = int(limit_usd * 1_000_000)
    summaries: dict[CompareMode, LiveModeSummary] = {
        CompareMode.UNGOVERNED: LiveModeSummary(mode=CompareMode.UNGOVERNED),
        CompareMode.TOKENOPS: LiveModeSummary(mode=CompareMode.TOKENOPS),
    }

    if mode_only:
        order = [CompareMode(mode_only)]
    else:
        order = [CompareMode.UNGOVERNED, CompareMode.TOKENOPS]

    batch_size = max(1, parallel_batch) if not mode_only else 1
    trial_nums = list(range(1, trials + 1))
    for start in range(0, len(trial_nums), batch_size):
        batch = trial_nums[start : start + batch_size]
        if len(batch) > 1:
            print(f"\n=== parallel batch trials {batch} ===", flush=True)
            batch_out = await asyncio.gather(
                *[
                    _run_single_trial(
                        t,
                        order=order,
                        scenario=scenario,
                        limit_micros=limit_micros,
                        max_steps=max_steps,
                        cooldown_sec=cooldown_sec,
                    )
                    for t in batch
                ]
            )
            for trial_out in batch_out:
                for mode, live in trial_out.items():
                    summaries[mode].trials.append(live)
        else:
            trial_out = await _run_single_trial(
                batch[0],
                order=order,
                scenario=scenario,
                limit_micros=limit_micros,
                max_steps=max_steps,
                cooldown_sec=cooldown_sec,
            )
            for mode, live in trial_out.items():
                summaries[mode].trials.append(live)

    for summary in summaries.values():
        summary.trials.sort(key=lambda t: t.trial)

    return ScenarioResult(
        scenario=scenario,
        ungoverned=summaries[CompareMode.UNGOVERNED],
        tokenops=summaries[CompareMode.TOKENOPS],
    )


async def async_main() -> int:
    load_env()
    scenario_names = list(ALL_SUITE)
    suite_choices = list(SUITE_BY_NAME)
    legacy = {
        "policy_suite": "fair_suite",
        "stress_suite": "trap_suite",
        "steer_suite": "cap_suite",
        "cost_showcase_suite": "showcase_suite",
    }
    parser = argparse.ArgumentParser(description="Live browser-use: vanilla vs TokenOps")
    parser.add_argument(
        "--scenario",
        choices=[*scenario_names, *suite_choices, *legacy],
        default="fair_suite",
        help="Scenario id or suite (fair, trap, cap, showcase)",
    )
    parser.add_argument("--limit-usd", type=float, default=None, help="Override scenario cap")
    parser.add_argument("--max-steps", type=int, default=None, help="Override scenario steps")
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument(
        "--parallel-batch",
        type=int,
        default=1,
        help="Run up to N trials concurrently (default 1 = sequential)",
    )
    parser.add_argument("--task", default=None, help="Override task text (ignores scenario body)")
    parser.add_argument("--mode-only", choices=["ungoverned", "tokenops"], default=None)
    parser.add_argument("--cooldown-sec", type=int, default=COOLDOWN_BETWEEN_ARMS_SEC)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    suite_key = legacy.get(args.scenario, args.scenario)
    active_suite: str | None = None
    if suite_key in SUITE_BY_NAME:
        scenario_ids = list(SUITE_BY_NAME[suite_key])
        active_suite = suite_key.removesuffix("_suite")
    else:
        scenario_ids = [args.scenario]

    results: list[ScenarioResult] = []
    for sid in scenario_ids:
        sc = get_scenario(sid)
        if args.task:
            sc = LiveScenario(
                id=sc.id,
                task=args.task,
                description=sc.description,
                default_limit_usd=sc.default_limit_usd,
                default_max_steps=sc.default_max_steps,
                suite=sc.suite,
            )
        limit_usd = args.limit_usd if args.limit_usd is not None else sc.default_limit_usd
        max_steps = args.max_steps if args.max_steps is not None else sc.default_max_steps
        results.append(
            await _run_scenario_ab(
                sc,
                limit_usd=limit_usd,
                max_steps=max_steps,
                trials=args.trials,
                mode_only=args.mode_only,
                cooldown_sec=args.cooldown_sec if not args.mode_only else 0,
                parallel_batch=args.parallel_batch,
            )
        )

    if args.as_json:
        payload = []
        for r in results:
            u, g = r.ungoverned, r.tokenops
            red = 0.0
            if u.avg_spend_usd > 0:
                red = round(100.0 * (u.avg_spend_usd - g.avg_spend_usd) / u.avg_spend_usd, 1)
            delta = u.avg_spend_usd - g.avg_spend_usd
            win = classify_win(
                ungoverned_spend=u.avg_spend_usd,
                tokenops_spend=g.avg_spend_usd,
                ungoverned_steps=u.avg_steps,
                tokenops_steps=g.avg_steps,
                ungoverned_success_within=u.success_within_budget_count,
                tokenops_success_within=g.success_within_budget_count,
                trials=args.trials,
            )

            def _arm(s: LiveModeSummary) -> dict:
                return {
                    "scored_trials": s.scored_trials,
                    "infra_trials": s.infra_trials,
                    "successes": s.successes,
                    "success_within_budget": s.success_within_budget_count,
                    "avg_spend_usd": round(s.avg_spend_usd, 6),
                    "median_spend_usd": round(s.median_spend_usd, 6),
                    "avg_steps": round(s.avg_steps, 2),
                    "avg_tokens": round(s.avg_tokens),
                }

            payload.append({
                "suite": active_suite or r.scenario.suite,
                "scenario": r.scenario.id,
                "trials": args.trials,
                "limit_usd": args.limit_usd or r.scenario.default_limit_usd,
                "ungoverned": _arm(u),
                "tokenops": _arm(g),
                "spend_reduction_pct": red,
                "delta_usd_per_trial": round(delta, 6),
                "savings_per_1k_runs_usd": round(delta * 1000, 2),
                "win_type": win,
                "showcase_pass": showcase_pass(
                    ungoverned_spend=u.avg_spend_usd,
                    tokenops_spend=g.avg_spend_usd,
                    ungoverned_success_within=u.success_within_budget_count,
                    tokenops_success_within=g.success_within_budget_count,
                ),
            })
        print(json.dumps(payload, indent=2))
    else:
        if active_suite:
            print(f"\n{'=' * 60}\nSuite: {active_suite}  ({len(results)} scenario(s), N={args.trials})\n{'=' * 60}")
        for r in results:
            if args.mode_only:
                s = r.ungoverned if args.mode_only == "ungoverned" else r.tokenops
                print(f"\n=== {r.scenario.id} ({args.mode_only}) ===")
                print(f"scored: {s.scored_trials}/{s.total_trials}  avg ${s.avg_spend_usd:.4f}")
            else:
                print("\n" + _format_summary(
                    r.ungoverned,
                    r.tokenops,
                    scenario=r.scenario,
                    limit_usd=args.limit_usd or r.scenario.default_limit_usd,
                    trials=args.trials,
                    suite=active_suite or r.scenario.suite,
                ))
    return 0


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
