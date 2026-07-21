#!/usr/bin/env python3
"""Seed a tight run budget for shared-ledger before/after screenshots.

Usage:
    python scripts/prep_ledger_comparison.py
    SEARCH_BACKEND=corpus make bench-ui
    # Simulator → Start run (demo mode) → capture screenshots

Sets run_llm_cap to $0.001 so demo research (~972 µ$) + summarize (~222 µ$)
exceeds cap when ledgers are independent; shared ledger enforces one cap.

Use SEARCH_BACKEND=corpus for reproducible simulator screenshots (no DuckDuckGo).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tokenops.control.models import BudgetSpec  # noqa: E402
from tokenops.control.store import Store  # noqa: E402
from tokenops.env import load_env  # noqa: E402

# Demo stub costs (healthy corpus, 1 search): research ~972 µ$, summarize ~222 µ$
# → total ~1,194 µ$. Cap below that so old mode completes over cap; shared ledger halts first.
TIGHT_CAP_MICROS = 1_000  # $0.001


def main() -> int:
    load_env()
    db = os.environ.get("TOKENOPS_DB", str(ROOT / "tokenops.db"))
    store = Store(db, auto_seed=False)
    if not store.list_policy_instances():
        store.reseed_governance()
    store.upsert_budget(
        BudgetSpec(id="run_llm_cap", limit_micros=TIGHT_CAP_MICROS, dimension="run"),
    )
    store.close()
    print(f"Set run_llm_cap to ${TIGHT_CAP_MICROS / 1_000_000:.4f} on {db}")
    print("Expected demo run total ~$0.0012 — over cap if agents do not share spend.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
