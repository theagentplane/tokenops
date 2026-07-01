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
    COST_SHOWCASE_SUITE,
    POLICY_SUITE,
    STEER_SUITE,
    STRESS_SUITE,
    LiveScenario,
    get_scenario,
)
from benchmarking.common.harness import BenchmarkMode, CompareMode, RunOutcome  # noqa: E402

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


@dataclass
class LiveModeSummary:
    mode: CompareMode
    trials: list[LiveTrial] = field(default_factory=list)

    def _spends(self) -> list[float]:
        return [t.outcome.spend_micros / 1_000_000 for t in self.trials]

    def _tokens(self) -> list[int]:
        return [t.total_tokens for t in self.trials]

    @property
    def avg_spend_usd(self) -> float:
        return mean(self._spends()) if self.trials else 0.0

    @property
    def median_spend_usd(self) -> float:
        return float(median(self._spends())) if self.trials else 0.0

    @property
    def avg_tokens(self) -> float:
        return mean(self._tokens()) if self.trials else 0.0

    @property
    def median_tokens(self) -> float:
        return float(median(self._tokens())) if self.trials else 0.0

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
        return LiveTrial(trial=0, mode=mode, outcome=outcome)

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
    return LiveTrial(
        trial=0,
        mode=mode,
        outcome=outcome,
        total_tokens=int(usage.get("total_tokens", 0)),
        browser_cost_usd=float(usage.get("browser_cost_usd", 0.0)),
        within_budget=within_budget,
        success_within_budget=success and within_budget,
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
            governance_preset=scenario.governance_preset,
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
        print(
            f"  spend ${spend_usd:.4f} ({budget_note})  steps {m.agent_steps}  "
            f"success={m.agent_success}  halted={getattr(m, 'halted', False)}",
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
) -> str:
    spend_red = _pct_reduction(base.avg_spend_usd, governed.avg_spend_usd)
    token_red = _pct_reduction(base.avg_tokens, governed.avg_tokens)
    lines = [
        f"=== {scenario.id}: ungoverned vs TokenOps ({trials} trial(s)) ===",
        f"    {scenario.description}",
        f"    TokenOps cap: ${limit_usd:.2f}  max_steps: {scenario.default_max_steps}",
        "",
        "Without TokenOps",
        f"   successes: {base.successes}/{trials}  success within ${limit_usd:.2f}: {base.success_within_budget_count}/{trials}",
        f"   avg spend: ${base.avg_spend_usd:.4f}  median ${base.median_spend_usd:.4f}",
        f"   avg tokens: {base.avg_tokens:,.0f}",
        "",
        "With TokenOps",
        f"   successes: {governed.successes}/{trials} (+{governed.successes - base.successes})",
        f"   success within cap: {governed.success_within_budget_count}/{trials} (+{governed.success_within_budget_count - base.success_within_budget_count})",
        f"   avg spend: ${governed.avg_spend_usd:.4f} ({spend_red:+.1f}% vs ungoverned)",
        f"   avg tokens: {governed.avg_tokens:,.0f} ({token_red:+.1f}% vs ungoverned)",
        "",
        "Per-trial:",
    ]
    for i in range(trials):
        u = base.trials[i] if i < len(base.trials) else None
        g = governed.trials[i] if i < len(governed.trials) else None
        if u and g:
            lines.append(
                f"  trial {i + 1}:  vanilla {'ok' if u.outcome.success else 'FAIL':4} "
                f"${u.outcome.spend_micros / 1_000_000:.4f} {u.total_tokens:,} tok  |  "
                f"TokenOps {'ok' if g.outcome.success else 'FAIL':4} "
                f"${g.outcome.spend_micros / 1_000_000:.4f} {g.total_tokens:,} tok"
            )
    return "\n".join(lines)


async def _run_scenario_ab(
    scenario: LiveScenario,
    *,
    limit_usd: float,
    max_steps: int,
    trials: int,
    mode_only: str | None,
    cooldown_sec: int,
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

    for trial in range(1, trials + 1):
        for i, mode in enumerate(order):
            if i > 0 and cooldown_sec > 0:
                print(f"\n… cooldown {cooldown_sec}s before {mode.value} …", flush=True)
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
                summaries[mode].trials.append(live)
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

    return ScenarioResult(
        scenario=scenario,
        ungoverned=summaries[CompareMode.UNGOVERNED],
        tokenops=summaries[CompareMode.TOKENOPS],
    )


async def async_main() -> int:
    load_env()
    scenario_names = list(
        dict.fromkeys([
            *POLICY_SUITE,
            *STRESS_SUITE,
            *STEER_SUITE,
            *COST_SHOWCASE_SUITE,
            "flight_sfo_india",
        ])
    )
    parser = argparse.ArgumentParser(description="Live browser-use: vanilla vs TokenOps")
    parser.add_argument(
        "--scenario",
        choices=[
            *scenario_names,
            "all",
            "policy_suite",
            "stress_suite",
            "steer_suite",
            "cost_showcase_suite",
        ],
        default="policy_suite",
        help=(
            "Task preset (default: policy_suite; cost_showcase_suite = 4 cost-optimization A/B demos)"
        ),
    )
    parser.add_argument("--limit-usd", type=float, default=None, help="Override scenario cap")
    parser.add_argument("--max-steps", type=int, default=None, help="Override scenario steps")
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--task", default=None, help="Override task text (ignores scenario body)")
    parser.add_argument("--mode-only", choices=["ungoverned", "tokenops"], default=None)
    parser.add_argument("--cooldown-sec", type=int, default=COOLDOWN_BETWEEN_ARMS_SEC)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    if args.scenario == "all":
        scenario_ids = scenario_names
    elif args.scenario == "policy_suite":
        scenario_ids = list(POLICY_SUITE)
    elif args.scenario == "stress_suite":
        scenario_ids = list(STRESS_SUITE)
    elif args.scenario == "steer_suite":
        scenario_ids = list(STEER_SUITE)
    elif args.scenario == "cost_showcase_suite":
        scenario_ids = list(COST_SHOWCASE_SUITE)
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
                governance_preset=sc.governance_preset,
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
            )
        )

    if args.as_json:
        payload = []
        for r in results:
            payload.append({
                "scenario": r.scenario.id,
                "limit_usd": args.limit_usd or r.scenario.default_limit_usd,
                "ungoverned": {
                    "successes": r.ungoverned.successes,
                    "success_within_budget": r.ungoverned.success_within_budget_count,
                    "avg_spend_usd": round(r.ungoverned.avg_spend_usd, 6),
                    "avg_tokens": round(r.ungoverned.avg_tokens),
                },
                "tokenops": {
                    "successes": r.tokenops.successes,
                    "success_within_budget": r.tokenops.success_within_budget_count,
                    "avg_spend_usd": round(r.tokenops.avg_spend_usd, 6),
                    "avg_tokens": round(r.tokenops.avg_tokens),
                },
            })
        print(json.dumps(payload, indent=2))
    else:
        for r in results:
            if args.mode_only:
                s = r.ungoverned if args.mode_only == "ungoverned" else r.tokenops
                print(f"\n=== {r.scenario.id} ({args.mode_only}) ===")
                print(f"successes: {s.successes}/{args.trials}  avg ${s.avg_spend_usd:.4f}")
            else:
                print("\n" + _format_summary(
                    r.ungoverned,
                    r.tokenops,
                    scenario=r.scenario,
                    limit_usd=args.limit_usd or r.scenario.default_limit_usd,
                    trials=args.trials,
                ))
    return 0


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
