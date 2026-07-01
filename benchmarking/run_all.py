#!/usr/bin/env python3
"""Run live browser-use benchmark (ungoverned vs TokenOps)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

LIVE = Path(__file__).resolve().parent / "browseruse" / "run_live_benchmark.py"


def main() -> int:
    return subprocess.run([sys.executable, str(LIVE), *sys.argv[1:]]).returncode


if __name__ == "__main__":
    raise SystemExit(main())
