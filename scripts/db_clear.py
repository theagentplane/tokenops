#!/usr/bin/env python3
"""Clear the TokenOps SQLite store (runs + governance).

Usage:
    python scripts/db_clear.py              # default tokenops.db
    python scripts/db_clear.py --db path    # custom path
    TOKENOPS_DB=other.db python scripts/db_clear.py

Stop servers/UI first if they hold the DB open (``make stop``).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tokenops.env import load_env  # noqa: E402

load_env()

from tokenops.control.store import Store  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Clear all rows in the TokenOps SQLite store.")
    parser.add_argument(
        "--db",
        default=os.environ.get("TOKENOPS_DB", "tokenops.db"),
        help="SQLite file path (default: TOKENOPS_DB or tokenops.db)",
    )
    args = parser.parse_args()

    store = Store(args.db, auto_seed=False)
    runs_before = len(store.list_runs())
    policies_before = len(store.list_policy_instances())
    store.clear_all()
    store.close()

    print(f"Cleared {args.db}: {runs_before} run(s), {policies_before} policy instance(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
