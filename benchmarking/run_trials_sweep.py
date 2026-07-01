#!/usr/bin/env python3
"""Run live A/B benchmarks at N=1,5,10 (or custom) and compare averaged results."""

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
        *extra,
    ]
    print(f"\n>>> {fw} | {scenario} | trials={trials}", flush=True)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout, file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        raise RuntimeError(f"{fw} trials={trials} failed (exit {proc.returncode})")
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
        all_rows.sort(key=lambda r: (r.get("framework", ""), r.get("trials", 0)))
        if out_path:
            out_path.write_text(json.dumps(all_rows, indent=2))


def _pending_jobs(
    targets: list[str],
    counts: list[int],
    done: set[tuple[str, int]],
    *,
    scenario: str,
    out_path: Path | None,
) -> list[tuple[str, int]]:
    jobs: list[tuple[str, int]] = []
    for fw in targets:
        for n in counts:
            if (fw, n) in done:
                print(f"\n>>> skip {fw} | {scenario} | trials={n} (already in {out_path})")
                continue
            jobs.append((fw, n))
    return jobs


def _print_table(rows: list[dict]) -> None:
    if not rows:
        return
    header = (
        f"{'framework':<12} {'scenario':<28} {'N':>3}  "
        f"{'vanilla $':>10} {'tokenops $':>10} {'red%':>6}  "
        f"{'v ok':>5} {'t ok':>5}  {'v steps':>8} {'t steps':>8}"
    )
    print("\n" + header)
    print("-" * len(header))
    for r in rows:
        u, g = r["ungoverned"], r["tokenops"]
        print(
            f"{r['framework']:<12} {r['scenario']:<28} {r['trials']:>3}  "
            f"${u['avg_spend_usd']:>9.4f} ${g['avg_spend_usd']:>9.4f} "
            f"{r.get('spend_reduction_pct', 0):>5.1f}%  "
            f"{u['successes']:>3}/{r['trials']:<1} {g['successes']:>3}/{r['trials']:<1}  "
            f"{u.get('avg_steps', 0):>8.1f} {g.get('avg_steps', 0):>8.1f}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Trial-count sweep for live A/B benchmarks")
    parser.add_argument("--framework", choices=[*FRAMEWORKS, "both"], default="both")
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--trial-counts", default="1,5,10", help="Comma-separated N values")
    parser.add_argument("--cooldown-sec", type=int, default=60)
    parser.add_argument(
        "--jobs",
        type=int,
        default=1,
        help="Max concurrent subprocesses (e.g. 2 to run N=5 and N=10 in parallel)",
    )
    parser.add_argument("--out", default=None, help="Write full JSON results to path")
    args, extra = parser.parse_known_args()

    if args.jobs < 1:
        parser.error("--jobs must be >= 1")

    counts = [int(x.strip()) for x in args.trial_counts.split(",") if x.strip()]
    targets = list(FRAMEWORKS) if args.framework == "both" else [args.framework]

    out_path = Path(args.out) if args.out else None
    all_rows: list[dict] = []
    done: set[tuple[str, int]] = set()
    if out_path and out_path.is_file():
        all_rows = json.loads(out_path.read_text())
        done = {(r["framework"], r["trials"]) for r in all_rows if "framework" in r}

    pending = _pending_jobs(
        targets, counts, done, scenario=args.scenario, out_path=out_path,
    )
    if not pending:
        _print_table(all_rows)
        if out_path:
            print(f"\nWrote {out_path}")
        return 0

    write_lock = threading.Lock()
    errors: list[str] = []

    def _worker(fw: str, n: int) -> None:
        try:
            row = _run_once(
                fw,
                scenario=args.scenario,
                trials=n,
                cooldown_sec=args.cooldown_sec,
                extra=extra,
            )
            row["framework"] = fw
            _append_row(all_rows, row, out_path=out_path, lock=write_lock)
            print(f"\n<<< done {fw} | {args.scenario} | trials={n}", flush=True)
        except Exception as exc:
            errors.append(f"{fw} trials={n}: {exc}")

    if args.jobs == 1:
        for fw, n in pending:
            _worker(fw, n)
    else:
        print(f"\nRunning {len(pending)} job(s) with --jobs {args.jobs}", flush=True)
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futures = [pool.submit(_worker, fw, n) for fw, n in pending]
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
