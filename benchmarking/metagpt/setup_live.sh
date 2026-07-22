#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="$ROOT/benchmarking/metagpt/.venv"
PY="${PYTHON:-python3.11}"
if ! command -v "$PY" >/dev/null 2>&1; then
  PY=python3.10
fi
"$PY" -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"
pip install -U pip
pip install -e "$ROOT"
pip install -e "$ROOT/benchmarking/metagpt/vendor"
echo "Ready:"
echo "  source benchmarking/metagpt/.venv/bin/activate"
echo "  python benchmarking/metagpt/run_live_benchmark.py --scenario baseline_suite"
