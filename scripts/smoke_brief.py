#!/usr/bin/env python3
"""Smoke-run Scout→Analyst→Editor against a live brief stack + budgets."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault("PYTHONPATH", str(ROOT))
os.environ.setdefault("TOKENOPS_CONFIG", "examples/config/brief.yaml")
os.environ.setdefault("TOKENOPS_URL", "http://localhost:7700")
os.environ.setdefault("TOKENOPS_DB", "tokenops.db")

from tokenops.env import load_env  # noqa: E402

load_env()

from examples.app_config import load_config  # noqa: E402
from examples.brief import submit_brief_sync_with_meta  # noqa: E402
from tokenops.control.store import Store  # noqa: E402


def main() -> int:
    cfg = load_config()
    topic = cfg.task or "Competitive brief on mid-market AI coding assistants"
    print(f"Submitting to Scout at {cfg.scout.url}")
    print(f"Topic: {topic}")
    result, meta = submit_brief_sync_with_meta(
        cfg.scout.url,
        topic,
        corpus_profile=cfg.corpus_profile,
        intent="brief-demo",
        user_dims={"demo": "brief"},
    )
    status = meta.get("status")
    cost = int(meta.get("cost_micros") or 0)
    run_id = meta.get("run_id")
    print("---")
    print(f"status:       {status}")
    print(f"run_id:       {run_id}")
    print(f"cost_micros:  {cost} (${cost / 1_000_000:.6f})")
    print(f"halt_reason:  {meta.get('halt_reason')}")
    print(f"angles:       {meta.get('angles')}")
    print(f"sections:     {meta.get('sections')}")
    print(f"findings:     {len(result.findings)}")
    print(f"brief[:400]:  {(result.summary or '')[:400]!r}")

    store = Store(os.environ.get("TOKENOPS_DB", "tokenops.db"), auto_seed=False)
    gov = store.governance_config_for("scout")
    budgets = gov.get("governance", {}).get("budgets", [])
    cap = next((b for b in budgets if b.get("id") == "run_llm_cap"), None)
    limit = None if not cap else cap.get("limit_micros")
    print("---")
    print(f"budget run_llm_cap limit_micros: {limit}")
    if limit is not None:
        print(f"under budget: {cost <= int(limit)}")

    ok = status == "completed" and bool(result.summary) and cost > 0
    if limit is not None:
        ok = ok and cost <= int(limit)
    if not ok:
        print("SMOKE FAILED", file=sys.stderr)
        return 1
    print("SMOKE OK — brief stack governed under run budget")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
