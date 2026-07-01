#!/usr/bin/env python3
"""Reseed governance (budgets + policies) from default.yaml.

Usage:
    python scripts/db_reseed.py                 # governance only
    python scripts/db_reseed.py --full          # clear runs too, then reseed
    python scripts/db_reseed.py --config path   # alternate YAML

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

from tokenops.config.loader import load_governance_yaml  # noqa: E402
from tokenops.control.store import Store  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Reseed governance from config YAML.")
    parser.add_argument(
        "--db",
        default=os.environ.get("TOKENOPS_DB", "tokenops.db"),
        help="SQLite file path (default: TOKENOPS_DB or tokenops.db)",
    )
    parser.add_argument(
        "--config",
        default=os.environ.get("TOKENOPS_CONFIG"),
        help="Config YAML with a governance: block (default: TOKENOPS_CONFIG or default.yaml)",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Also clear run history and registrations before reseeding",
    )
    args = parser.parse_args()

    governance = load_governance_yaml(args.config) if args.config else load_governance_yaml()
    if not governance:
        print("No governance block found in config YAML.", file=sys.stderr)
        return 1

    store = Store(args.db, auto_seed=False)
    if args.full:
        store.clear_all()
    ok = store.reseed_governance(governance)
    budgets = len(store.list_budgets())
    policies = len(store.list_policy_instances())
    store.close()

    if not ok:
        print("Reseed produced no governance rows.", file=sys.stderr)
        return 1

    scope = "full store" if args.full else "governance"
    print(f"Reseeded {args.db} ({scope}): {budgets} budget(s), {policies} policy instance(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
