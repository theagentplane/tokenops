#!/usr/bin/env bash
# Python 3.11+ venv for live browser-use.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="$ROOT/benchmarking/browseruse/.venv"
PY="${PYTHON:-python3.12}"
if ! command -v "$PY" >/dev/null 2>&1; then
  PY=python3.11
fi
"$PY" -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"
pip install -U pip
pip install -e "$ROOT"
pip install -e "$ROOT/benchmarking/browseruse/vendor"
echo "Ready:"
echo "  source benchmarking/browseruse/.venv/bin/activate"
echo "  python benchmarking/run_all.py --trials 1 --limit-usd 1.00 --max-steps 25"
