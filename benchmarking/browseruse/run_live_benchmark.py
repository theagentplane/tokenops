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
from benchmarking.browseruse.scenarios_live import FLIGHT_SFO_INDIA  # noqa: E402
from benchmarking.common.harness import BenchmarkMode, CompareMode, RunOutcome  # noqa: E402

LIVE_DEFAULT_LIMIT_USD = 1.00


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
        spend = int(round(usage.get("browser_cost_usd", 0.0) * 1_000_000)) or m.spend_micros
        success = bool(m.agent_success)
        halted = False
    else:
        spend = m.spend_micros
        success = result.success and not m.halted
        halted = m.halted

    within_budget = spend <= limit_micros and not halted
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
    task: str,
    limit_micros: int,
    max_steps: int,
    trial: int,
) -> GovernedRunResult:
    agent, llm_name = _make_agent(task)
    print(f"\n--- trial {trial} | {mode.value} ({llm_name}) ---", flush=True)

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
        )

    m = result.metrics
    usage = _usage_from_history(result.history)
    if m:
        cap = limit_micros / 1_000_000
        spend_usd = (
            usage.get("browser_cost_usd", m.spend_micros / 1_000_000)
            if mode is CompareMode.UNGOVERNED
            else m.spend_micros / 1_000_000
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
    limit_usd: float,
    trials: int,
    task_label: str,
) -> str:
    spend_red = _pct_reduction(base.avg_spend_usd, governed.avg_spend_usd)
    token_red = _pct_reduction(base.avg_tokens, governed.avg_tokens)
    lines = [
        f"=== browser-use live: ungoverned vs TokenOps ({trials} trial(s)) ===",
        f"task: {task_label[:80]}{'…' if len(task_label) > 80 else ''}",
        f"TokenOps budget cap: ${limit_usd:.2f}",
        "",
        "Without TokenOps (vanilla browser-use)",
        f"   avg spend: ${base.avg_spend_usd:.4f}  median ${base.median_spend_usd:.4f}",
        f"   avg tokens: {base.avg_tokens:,.0f}  median {base.median_tokens:,.0f}",
        f"   successes: {base.successes}/{trials}",
        "",
        "With TokenOps",
        f"   avg spend: ${governed.avg_spend_usd:.4f} ({spend_red:+.1f}% vs ungoverned)",
        f"   median spend: ${governed.median_spend_usd:.4f}",
        f"   avg tokens: {governed.avg_tokens:,.0f} ({token_red:+.1f}% vs ungoverned)",
        f"   successes: {governed.successes}/{trials} (+{governed.successes - base.successes})",
        f"   success within cap: {governed.success_within_budget_count}/{trials}",
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


async def async_main() -> int:
    load_env()
    parser = argparse.ArgumentParser(description="Live browser-use: vanilla vs TokenOps")
    parser.add_argument("--limit-usd", type=float, default=LIVE_DEFAULT_LIMIT_USD)
    parser.add_argument("--max-steps", type=int, default=25)
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--task", default=FLIGHT_SFO_INDIA)
    parser.add_argument("--mode-only", choices=["ungoverned", "tokenops"], default=None)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    limit_micros = int(args.limit_usd * 1_000_000)
    scenario_id = "live_task"
    modes = (
        [CompareMode(args.mode_only)]
        if args.mode_only
        else [CompareMode.UNGOVERNED, CompareMode.TOKENOPS]
    )
    summaries: dict[CompareMode, LiveModeSummary] = {
        m: LiveModeSummary(mode=m) for m in modes
    }

    for trial in range(1, args.trials + 1):
        for mode in modes:
            try:
                res = await _run_trial(
                    mode,
                    task=args.task,
                    limit_micros=limit_micros,
                    max_steps=args.max_steps,
                    trial=trial,
                )
                live = _trial_from_result(
                    res, mode=mode, scenario_id=scenario_id, limit_micros=limit_micros,
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
                            scenario_id=scenario_id,
                            success=False,
                            spend_micros=0,
                            steps=0,
                            halt_reason=str(exc),
                        ),
                    )
                )

    if len(modes) == 2:
        base = summaries[CompareMode.UNGOVERNED]
        gov = summaries[CompareMode.TOKENOPS]
        if not args.as_json:
            print("\n" + _format_summary(
                base, gov, limit_usd=args.limit_usd, trials=args.trials, task_label=args.task,
            ))
    return 0


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
