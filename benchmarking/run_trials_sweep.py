#!/usr/bin/env python3
"""Run live A/B benchmarks at N=1,3,5 (or custom) and compare averaged results."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent

FRAMEWORKS = {
    "browseruse": ROOT / "browseruse" / "run_live_benchmark.py",
    "metagpt": ROOT / "metagpt" / "run_live_benchmark.py",
}

VENV_PYTHON = {
    "browseruse": ROOT / "browseruse" / ".venv" / "bin" / "python",
    "metagpt": ROOT / "metagpt" / ".venv" / "bin" / "python",
}

SHOWCASE_SCENARIOS = {
    "browseruse": ("books_verify_trap",),
    "metagpt": ("pricing_quick_verify_trap", "pricing_model_routing"),
}


def _python(fw: str) -> str:
    candidate = VENV_PYTHON[fw]
    return str(candidate) if candidate.is_file() else sys.executable


def _extract_json(stdout: str, stderr: str = "") -> dict:
    """Parse benchmark --json payload (logs may pollute stdout)."""
    decoder = json.JSONDecoder()
    for text in (stdout, stderr, stdout + "\n" + stderr):
        found: list = []
        i = 0
        while i < len(text):
            if text[i] not in "[{":
                i += 1
                continue
            try:
                obj, end = decoder.raw_decode(text, i)
                found.append(obj)
                i += end
            except json.JSONDecodeError:
                i += 1
        for raw in reversed(found):
            candidate = raw[0] if isinstance(raw, list) and raw else raw
            if isinstance(candidate, dict) and "ungoverned" in candidate and "tokenops" in candidate:
                return candidate

    combined = stdout + "\n" + stderr
    match = re.search(r'\[\s*\{\s*"scenario"\s*:', combined)
    if match:
        obj, _ = decoder.raw_decode(combined, match.start())
        if isinstance(obj, list) and obj:
            return obj[0]
    raise RuntimeError(f"no benchmark payload in output:\n{combined[-3000:]}")


def _run_once(
    fw: str,
    *,
    scenario: str,
    trials: int,
    cooldown_sec: int,
    parallel_batch: int,
    extra: list[str],
) -> dict:
    script = FRAMEWORKS[fw]
    cmd = [
        _python(fw),
        str(script),
        "--scenario",
        scenario,
        "--trials",
        str(trials),
        "--cooldown-sec",
        str(cooldown_sec),
        "--json",
    ]
    if parallel_batch > 1:
        cmd.extend(["--parallel-batch", str(parallel_batch)])
    cmd.extend(extra)
    print(f"\n>>> {fw} | {scenario} | trials={trials} batch={parallel_batch}", flush=True)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout, file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        raise RuntimeError(f"{fw} {scenario} trials={trials} failed (exit {proc.returncode})")
    return _extract_json(proc.stdout, proc.stderr)


def _append_row(
    all_rows: list[dict],
    row: dict,
    *,
    out_path: Path | None,
    lock: threading.Lock,
) -> None:
    with lock:
        all_rows.append(row)
        all_rows.sort(
            key=lambda r: (r.get("framework", ""), r.get("scenario", ""), r.get("trials", 0))
        )
        if out_path:
            out_path.write_text(json.dumps(all_rows, indent=2))


def _job_key(row: dict) -> tuple[str, str, int]:
    return (row["framework"], row["scenario"], row["trials"])


def _expand_scenarios(framework: str, scenario: str | None, suite: str | None) -> list[str]:
    if suite == "showcase_suite":
        return list(SHOWCASE_SCENARIOS[framework])
    if scenario:
        return [scenario]
    raise ValueError("provide --scenario or --suite showcase_suite")


def _partition_jobs(pending: list[tuple[str, str, int]]) -> tuple[list, list, list]:
    """Split pending into N=1, mid (2–4), and N>=5 buckets."""
    n1: list[tuple[str, str, int]] = []
    mid: list[tuple[str, str, int]] = []
    heavy: list[tuple[str, str, int]] = []
    for job in pending:
        _, _, n = job
        if n == 1:
            n1.append(job)
        elif n >= 5:
            heavy.append(job)
        else:
            mid.append(job)
    return n1, mid, heavy


def _print_table(rows: list[dict]) -> None:
    if not rows:
        return
    header = (
        f"{'framework':<12} {'scenario':<28} {'N':>3}  "
        f"{'vanilla $':>10} {'tokenops $':>10} {'red%':>6}  "
        f"{'showcase':>8}  {'win':>12}  "
        f"{'v ok':>5} {'t ok':>5}"
    )
    print("\n" + header)
    print("-" * len(header))
    for r in rows:
        u, g = r["ungoverned"], r["tokenops"]
        scored = u.get("scored_trials", r["trials"])
        print(
            f"{r['framework']:<12} {r['scenario']:<28} {r['trials']:>3}  "
            f"${u['avg_spend_usd']:>9.4f} ${g['avg_spend_usd']:>9.4f} "
            f"{r.get('spend_reduction_pct', 0):>5.1f}%  "
            f"{str(r.get('showcase_pass', '')):>8}  {r.get('win_type', ''):>12}  "
            f"{u['successes']:>3}/{scored:<1} {g['successes']:>3}/{scored:<1}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Trial-count sweep for live A/B benchmarks")
    parser.add_argument("--framework", choices=[*FRAMEWORKS, "both"], default="both")
    parser.add_argument("--scenario", default=None, help="Single scenario id")
    parser.add_argument(
        "--suite",
        choices=["showcase_suite"],
        default=None,
        help="Run all showcase scenarios for each selected framework",
    )
    parser.add_argument("--trial-counts", default="1,3,5", help="Comma-separated N values")
    parser.add_argument("--cooldown-sec", type=int, default=60)
    parser.add_argument(
        "--parallel-batch",
        type=int,
        default=3,
        help="Trial concurrency inside each run when N>=5 (default 3; use 1 on laptop)",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=2,
        help="Max concurrent subprocesses for N>=5 runs (default 2 local-friendly)",
    )
    parser.add_argument("--out", default=None, help="Write full JSON results to path")
    args, extra = parser.parse_known_args()

    if not args.scenario and not args.suite:
        parser.error("provide --scenario or --suite showcase_suite")
    if args.jobs < 1:
        parser.error("--jobs must be >= 1")

    counts = [int(x.strip()) for x in args.trial_counts.split(",") if x.strip()]
    targets = list(FRAMEWORKS) if args.framework == "both" else [args.framework]

    out_path = Path(args.out) if args.out else None
    all_rows: list[dict] = []
    done: set[tuple[str, str, int]] = set()
    if out_path and out_path.is_file():
        all_rows = json.loads(out_path.read_text())
        done = {_job_key(r) for r in all_rows if "framework" in r}

    pending: list[tuple[str, str, int]] = []
    for fw in targets:
        for scenario in _expand_scenarios(fw, args.scenario, args.suite):
            for n in counts:
                key = (fw, scenario, n)
                if key in done:
                    print(f"\n>>> skip {fw} | {scenario} | trials={n} (already in {out_path})")
                    continue
                pending.append(key)

    if not pending:
        _print_table(all_rows)
        if out_path:
            print(f"\nWrote {out_path}")
        return 0

    write_lock = threading.Lock()
    errors: list[str] = []

    def _worker(fw: str, scenario: str, n: int) -> None:
        try:
            batch = args.parallel_batch if n >= 5 else 1
            row = _run_once(
                fw,
                scenario=scenario,
                trials=n,
                cooldown_sec=args.cooldown_sec,
                parallel_batch=batch,
                extra=extra,
            )
            row["framework"] = fw
            _append_row(all_rows, row, out_path=out_path, lock=write_lock)
            print(f"\n<<< done {fw} | {scenario} | trials={n}", flush=True)
        except Exception as exc:
            errors.append(f"{fw} {scenario} trials={n}: {exc}")

    n1_jobs, mid_jobs, heavy_jobs = _partition_jobs(pending)

    for fw, scenario, n in n1_jobs:
        _worker(fw, scenario, n)

    if mid_jobs:
        print(f"\nRunning {len(mid_jobs)} mid-N job(s) sequentially (N=2–4)", flush=True)
        for fw, scenario, n in mid_jobs:
            _worker(fw, scenario, n)

    if heavy_jobs:
        print(f"\nRunning {len(heavy_jobs)} N>=5 job(s) with --jobs {args.jobs}", flush=True)
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futures = [pool.submit(_worker, fw, sc, n) for fw, sc, n in heavy_jobs]
            for fut in as_completed(futures):
                fut.result()

    if errors:
        for msg in errors:
            print(msg, file=sys.stderr)
        return 1

    _print_table(all_rows)
    if out_path:
        print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
