#!/usr/bin/env python3
"""Live browser-use bench for trajectory_hint: fire rate, SimHash hits, cost delta.

Phases:
  1. seed   — index a successful run (steering_trajectory)
  2. matrix — repeat task variants; report hint fire + match type (exact/simhash/miss)
  3. cost   — steering vs steering_trajectory on hits; report token/cost delta

Example:
  benchmarking/browseruse/.venv/bin/python benchmarking/browseruse/run_trajectory_hint_bench.py \\
    --phase all --scenario example_tight_cap --pause-seconds 90
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from tokenops.env import load_env  # noqa: E402

from benchmarking.browseruse.integration import install, run_governed  # noqa: E402
from benchmarking.browseruse.scenarios_live import EXAMPLE_TIGHT_CAP, get_scenario  # noqa: E402
from benchmarking.browseruse.session import GovernedRunMetrics  # noqa: E402
from benchmarking.common.harness import BenchmarkMode  # noqa: E402
from tokenops.control.models import RunRegistration  # noqa: E402
from tokenops.control.store import Store  # noqa: E402
from tokenops.control.trajectory.scope import (  # noqa: E402
    input_hash,
    input_simhash,
    scope_key,
    simhash_as_sqlite,
)
from tokenops.control.policies._util import hamming  # noqa: E402

DEFAULT_DB = ROOT / "benchmarking" / "browseruse" / ".trajectory_bench.db"


@dataclass
class TaskVariant:
    id: str
    task: str
    note: str = ""


@dataclass
class RunRow:
    variant_id: str
    preset: str
    phase: str
    metrics: GovernedRunMetrics | None
    total_tokens: int = 0
    cost_usd: float = 0.0
    error: str | None = None
    offline_match: str | None = None  # predicted from index before run


@dataclass
class BenchReport:
    scenario_id: str
    seed: RunRow | None = None
    matrix: list[RunRow] = field(default_factory=list)
    cost_pairs: list[dict] = field(default_factory=list)


def _task_variants(base_task: str) -> list[TaskVariant]:
    normalized_words = base_task.split()
    reorder = " ".join([normalized_words[1], normalized_words[0], *normalized_words[2:]])
    subtle = f"Please complete this task carefully.\n{base_task}"
    different = """
On https://example.com, report only the domain name shown in the browser address bar.
Call done with success=true. Do not read body text.
""".strip()
    return [
        TaskVariant("exact", base_task, "byte-identical task"),
        TaskVariant("word_reorder", reorder, "first two words swapped (SimHash probe)"),
        TaskVariant("subtle_prefix", subtle, "extra preamble (likely miss)"),
        TaskVariant("different_task", different, "unrelated goal (miss)"),
    ]


def _offline_lookup(store: Store, task: str) -> str | None:
    reg = RunRegistration(run_id="", intent="browseruse")
    sk = scope_key(reg, "browseruse", ["intent", "agent"])
    hit = store.lookup_trajectory_index(
        scope_key=sk,
        input_hash=input_hash(task),
        input_simhash=simhash_as_sqlite(input_simhash(task)),
        max_age_days=30,
        simhash_threshold=4,
    )
    return hit["match"] if hit else None


def _simhash_distance(a: str, b: str) -> int:
    return hamming(input_simhash(a), input_simhash(b))


def _make_agent(task: str):
    from browser_use import Agent, Browser, ChatOpenAI

    if not os.getenv("OPENAI_API_KEY") and not os.getenv("BROWSER_USE_API_KEY"):
        raise RuntimeError("Set OPENAI_API_KEY or BROWSER_USE_API_KEY")
    if os.getenv("BROWSER_USE_API_KEY"):
        from browser_use import ChatBrowserUse

        llm = ChatBrowserUse()
        name = "ChatBrowserUse"
    else:
        llm = ChatOpenAI(model="gpt-4o-mini")
        name = "ChatOpenAI(gpt-4o-mini)"
    browser = Browser(headless=True)
    agent = Agent(task=task, llm=llm, browser=browser, calculate_cost=True)
    return agent, name


def _usage(history) -> tuple[int, float]:
    usage = getattr(history, "usage", None) if history else None
    if usage is None:
        return 0, 0.0
    return (
        int(getattr(usage, "total_tokens", 0) or 0),
        float(getattr(usage, "total_cost", 0.0) or 0.0),
    )


async def _run_one(
    *,
    task: str,
    preset: str,
    limit_micros: int,
    max_steps: int,
    trajectory_db: str,
    phase: str,
    variant_id: str,
) -> RunRow:
    agent, llm_name = _make_agent(task)
    print(f"\n--- {phase} | {variant_id} | {preset} ({llm_name}) ---", flush=True)
    store = Store(trajectory_db, auto_seed=False)
    offline = _offline_lookup(store, task) if preset == "steering_trajectory" else None
    store.close()

    install()
    result = await run_governed(
        agent,
        mode=BenchmarkMode.TOKENOPS,
        limit_micros=limit_micros,
        live_pricing=True,
        max_steps=max_steps,
        governance_preset=preset,
        trajectory_db=trajectory_db,
        sync_trajectory_index=True,
    )
    tokens, cost = _usage(result.history)
    m = result.metrics
    row = RunRow(
        variant_id=variant_id,
        preset=preset,
        phase=phase,
        metrics=m,
        total_tokens=tokens,
        cost_usd=cost or (m.spend_micros / 1_000_000 if m else 0.0),
        error=result.error,
        offline_match=offline,
    )
    if m:
        print(
            f"  cost=${row.cost_usd:.4f} tokens={tokens:,} steps={m.agent_steps} "
            f"success={m.agent_success} halted={m.halted}",
            flush=True,
        )
        print(
            f"  hint: fired={m.trajectory_hint_fired} match={m.trajectory_hint_match} "
            f"chars={m.trajectory_hint_chars} offline_predicted={offline}",
            flush=True,
        )
    if result.error:
        print(f"  error: {result.error}", flush=True)
    return row


async def _pause_between_runs(seconds: float, *, before: str) -> None:
    if seconds <= 0:
        return
    print(f"  pausing {seconds:.0f}s before {before} (rate-limit cushion)...", flush=True)
    await asyncio.sleep(seconds)


async def run_bench(
    *,
    scenario_id: str,
    trajectory_db: str,
    phase: str,
    limit_usd: float | None,
    max_steps: int | None,
    pause_seconds: float,
) -> BenchReport:
    scenario = get_scenario(scenario_id)
    limit_micros = int(round((limit_usd or scenario.default_limit_usd) * 1_000_000))
    max_steps = max_steps or scenario.default_max_steps
    base_task = scenario.task.strip()
    variants = _task_variants(base_task)

    print(f"Scenario: {scenario.id}  cap=${limit_micros/1e6:.2f}  max_steps={max_steps}")
    print(f"Trajectory DB: {trajectory_db}")
    for v in variants:
        if v.id == "exact":
            continue
        print(f"  simhash dist vs exact [{v.id}]: {_simhash_distance(base_task, v.task)}")

    report = BenchReport(scenario_id=scenario.id)

    if phase in ("all", "seed", "cost"):
        print("\n== SEED (index builder) ==")
        report.seed = await _run_one(
            task=base_task,
            preset="steering_trajectory",
            limit_micros=limit_micros,
            max_steps=max_steps,
            trajectory_db=trajectory_db,
            phase="seed",
            variant_id="exact",
        )
        if not report.seed.metrics or not report.seed.metrics.agent_success:
            print("WARNING: seed run did not succeed — index may be empty", flush=True)
        if phase in ("all", "matrix"):
            await _pause_between_runs(pause_seconds, before="hit-rate matrix")

    if phase in ("all", "matrix"):
        print("\n== HIT-RATE MATRIX (steering_trajectory) ==")
        matrix_variants = [v for v in variants if not (phase == "matrix" and v.id == "exact")]
        for i, v in enumerate(matrix_variants):
            if i > 0:
                await _pause_between_runs(pause_seconds, before=f"matrix | {v.id}")
            row = await _run_one(
                task=v.task,
                preset="steering_trajectory",
                limit_micros=limit_micros,
                max_steps=max_steps,
                trajectory_db=trajectory_db,
                phase="matrix",
                variant_id=v.id,
            )
            report.matrix.append(row)
        if phase in ("all", "cost"):
            await _pause_between_runs(pause_seconds, before="cost delta")

    if phase in ("all", "cost"):
        print("\n== COST DELTA (steering vs steering_trajectory on exact repeat) ==")
        baseline = await _run_one(
            task=base_task,
            preset="steering",
            limit_micros=limit_micros,
            max_steps=max_steps,
            trajectory_db=trajectory_db,
            phase="cost_baseline",
            variant_id="exact",
        )
        await _pause_between_runs(pause_seconds, before="cost_hinted")
        hinted = await _run_one(
            task=base_task,
            preset="steering_trajectory",
            limit_micros=limit_micros,
            max_steps=max_steps,
            trajectory_db=trajectory_db,
            phase="cost_hinted",
            variant_id="exact",
        )
        if baseline.metrics and hinted.metrics:
            b_cost, h_cost = baseline.cost_usd, hinted.cost_usd
            b_tok, h_tok = baseline.total_tokens, hinted.total_tokens
            pct = round(100 * (b_cost - h_cost) / b_cost, 2) if b_cost > 0 else 0.0
            report.cost_pairs.append({
                "variant": "exact",
                "baseline_cost_usd": b_cost,
                "hinted_cost_usd": h_cost,
                "cost_delta_pct": pct,
                "baseline_tokens": b_tok,
                "hinted_tokens": h_tok,
                "hint_fired": hinted.metrics.trajectory_hint_fired,
                "hint_match": hinted.metrics.trajectory_hint_match,
            })

    return report


def _summarize(report: BenchReport) -> dict:
    matrix = []
    for r in report.matrix:
        m = r.metrics
        matrix.append({
            "variant": r.variant_id,
            "offline_predicted": r.offline_match,
            "hint_fired": m.trajectory_hint_fired if m else False,
            "hint_match": m.trajectory_hint_match if m else None,
            "cost_usd": r.cost_usd,
            "tokens": r.total_tokens,
            "success": m.agent_success if m else False,
        })

    fired = [x for x in matrix if x["hint_fired"]]
    return {
        "scenario": report.scenario_id,
        "seed_success": report.seed.metrics.agent_success if report.seed and report.seed.metrics else None,
        "matrix": matrix,
        "hit_rate": len(fired) / len(matrix) if matrix else 0.0,
        "exact_hits": sum(1 for x in matrix if x["hint_match"] == "exact"),
        "simhash_hits": sum(1 for x in matrix if x["hint_match"] == "simhash"),
        "cost_pairs": report.cost_pairs,
    }


def main() -> None:
    load_env()
    p = argparse.ArgumentParser(description="Trajectory hint browser-use live bench")
    p.add_argument("--scenario", default=EXAMPLE_TIGHT_CAP.id)
    p.add_argument("--phase", choices=["all", "seed", "matrix", "cost"], default="all")
    p.add_argument("--trajectory-db", default=str(DEFAULT_DB))
    p.add_argument("--limit-usd", type=float, default=None)
    p.add_argument("--max-steps", type=int, default=None)
    p.add_argument("--fresh-db", action="store_true", help="Delete trajectory DB before run")
    p.add_argument(
        "--pause-seconds",
        type=float,
        default=90.0,
        help="Seconds to wait between runs (TPM rate-limit cushion; default 90)",
    )
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    if args.fresh_db and Path(args.trajectory_db).exists():
        Path(args.trajectory_db).unlink()

    report = asyncio.run(
        run_bench(
            scenario_id=args.scenario,
            trajectory_db=args.trajectory_db,
            phase=args.phase,
            limit_usd=args.limit_usd,
            max_steps=args.max_steps,
            pause_seconds=args.pause_seconds,
        )
    )
    summary = _summarize(report)

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print("\n== SUMMARY ==")
        print(f"seed_success: {summary['seed_success']}")
        print(f"hit_rate: {summary['hit_rate']:.0%} ({len([x for x in summary['matrix'] if x['hint_fired']])}/{len(summary['matrix'])})")
        print(f"exact_hits: {summary['exact_hits']}  simhash_hits: {summary['simhash_hits']}")
        for row in summary["matrix"]:
            print(
                f"  {row['variant']:16} offline={row['offline_predicted']} "
                f"fired={row['hint_fired']} match={row['hint_match']} "
                f"${row['cost_usd']:.4f} {row['tokens']:,} tok"
            )
        for pair in summary["cost_pairs"]:
            print(
                f"cost delta [{pair['variant']}]: baseline=${pair['baseline_cost_usd']:.4f} "
                f"hinted=${pair['hinted_cost_usd']:.4f} ({pair['cost_delta_pct']:+.1f}%) "
                f"hint_fired={pair['hint_fired']} match={pair['hint_match']}"
            )


if __name__ == "__main__":
    main()
