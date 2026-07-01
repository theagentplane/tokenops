"""Bootstrap MetaGPT config from ``.env`` before vendor ``config2`` loads."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def bootstrap_metagpt_from_env() -> None:
    """Ensure ``metagpt.config2`` can load with ``OPENAI_API_KEY`` from the environment."""
    if "metagpt.config2" in sys.modules:
        return

    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("METAGPT_API_KEY")
    if not api_key:
        raise RuntimeError("Set OPENAI_API_KEY in .env for live MetaGPT benchmarks")

    model = os.getenv("METAGPT_BENCH_MODEL", "gpt-4o-mini")
    config_dir = Path.home() / ".metagpt"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config2.yaml").write_text(
        f"llm:\n"
        f"  api_type: openai\n"
        f"  api_key: {api_key}\n"
        f"  model: {model}\n"
        f"  base_url: {os.getenv('OPENAI_BASE_URL', 'https://api.openai.com/v1')}\n",
        encoding="utf-8",
    )

    import importlib

    const = importlib.import_module("metagpt.const")
    const.CONFIG_ROOT = config_dir
    importlib.import_module("metagpt.config2")
