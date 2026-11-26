#!/usr/bin/env python3
"""Write the Claude Code plugin's price file from the framework price book.

The plugin runs without the ``agent-tokenops`` package installed, so it cannot import
``tokenops.framework.pricing``. Its prices are generated from it instead, so the repository
keeps one price source (ADR 0009). Run ``python scripts/sync-claude-prices.py`` after changing
``DEFAULT_RATES``; ``tests/claude_code`` fails while the file is stale.
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
TARGET = ROOT / "integrations" / "claude-code" / "scripts" / "tokenops_cc" / "prices.json"


def rendered() -> str:
    from tokenops.framework.pricing import CACHE_WRITE_1H, CACHE_WRITE_5M, DEFAULT_RATES

    models = {
        name: {
            "input": r.input / 1e6,
            "output": r.output / 1e6,
            "cache_read": (r.cached if r.cached is not None else r.input // 2) / 1e6,
        }
        for name, r in sorted(DEFAULT_RATES.items())
        if name.startswith("claude-")
    }
    data = {
        "_generated": "by scripts/sync-claude-prices.py from tokenops.framework.pricing; USD per 1M tokens",
        "cache_write_5m": CACHE_WRITE_5M,
        "cache_write_1h": CACHE_WRITE_1H,
        "models": models,
    }
    return json.dumps(data, indent=1) + "\n"


if __name__ == "__main__":
    TARGET.write_text(rendered(), encoding="utf-8")
    print(f"wrote {TARGET.relative_to(ROOT)}")
