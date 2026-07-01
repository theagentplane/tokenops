#!/usr/bin/env python3
"""Run live agent benchmarks (browser-use and/or MetaGPT)."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FRAMEWORKS = {
    "browseruse": ROOT / "browseruse" / "run_live_benchmark.py",
    "metagpt": ROOT / "metagpt" / "run_live_benchmark.py",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run live TokenOps A/B benchmarks")
    parser.add_argument(
        "--framework",
        choices=[*FRAMEWORKS.keys(), "all"],
        default="browseruse",
        help="Which live benchmark to run (default: browseruse)",
    )
    args, extra = parser.parse_known_args()

    targets = list(FRAMEWORKS.keys()) if args.framework == "all" else [args.framework]
    rc = 0
    for fw in targets:
        script = FRAMEWORKS[fw]
        if not script.is_file():
            print(f"missing {script}", file=sys.stderr)
            return 1
        print(f"\n{'=' * 60}\nRunning {fw} live benchmark\n{'=' * 60}", flush=True)
        proc = subprocess.run([sys.executable, str(script), *extra])
        if proc.returncode != 0:
            rc = proc.returncode
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
