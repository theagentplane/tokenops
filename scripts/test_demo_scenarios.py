#!/usr/bin/env python3
"""Verify the three Chat demo scenarios against live LLM agents."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from examples.a2a.client import check_health_sync, submit_task_sync_with_meta  # noqa: E402
from examples.app_config import load_config  # noqa: E402
from tokenops.control.models import GovernanceMode  # noqa: E402
from tokenops.control.store import Store  # noqa: E402
from tokenops.env import load_env  # noqa: E402
from examples.ui.demo_chips import live_governance_banner, prepare_chip_governance  # noqa: E402


def _assert(name: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        raise SystemExit(1)


def main() -> int:
    load_env()
    cfg = load_config()
    if not check_health_sync(cfg.research.url):
        print("Research server offline — run `make run` first")
        return 1

    store = Store()

    # 1. Governance OFF — spend exceed (cost_cap chip, preview)
    prepare_chip_governance(store, "cost_cap")
    chip = prepare_chip_governance(store, "cost_cap")
    _, meta = submit_task_sync_with_meta(
        cfg.research.url,
        chip.prompt,
        corpus_profile="healthy",
        intent="test_preview_exceed",
        governance_mode=GovernanceMode.PREVIEW,
    )
    cost = int(meta["cost_micros"])
    _assert(
        "governance OFF — spend exceed",
        meta["status"] == "completed" and cost > chip.budget_micros,
        f"status={meta['status']} cost={cost} budget={chip.budget_micros}",
    )

    # 2. Governance ON — budget cap (cost_cap chip, enforce)
    chip = prepare_chip_governance(store, "cost_cap")
    _, meta = submit_task_sync_with_meta(
        cfg.research.url,
        chip.prompt,
        corpus_profile="healthy",
        intent="test_budget_cap",
        governance_mode=GovernanceMode.ENFORCE,
    )
    _assert(
        "governance ON — budget cap",
        meta["status"] == "halted" and bool(meta.get("halt_reason")),
        f"status={meta['status']} reason={meta.get('halt_reason')}",
    )

    # 3. Governance ON — cost guard (cost_guard chip, enforce)
    chip = prepare_chip_governance(store, "cost_guard")
    _, meta = submit_task_sync_with_meta(
        cfg.research.url,
        chip.prompt,
        corpus_profile="healthy",
        intent="test_cost_guard",
        governance_mode=GovernanceMode.ENFORCE,
    )
    events = list(meta.get("governance_events") or [])
    guard_hit = any(ev.get("policy") == "cost_guard" for ev in events)
    banner = live_governance_banner("cost_guard", meta, governance_mode=GovernanceMode.ENFORCE)
    _assert(
        "governance ON — cost guard",
        meta["status"] == "completed" and guard_hit and "cost guard" in banner.lower(),
        f"status={meta['status']} events={events} banner={banner}",
    )

    print("\nAll three scenarios passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
