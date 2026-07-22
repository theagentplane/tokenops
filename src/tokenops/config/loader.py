"""Governance YAML loading for the TokenOps control plane.

Agent/server bench config lives under ``examples.app_config``.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

DEFAULT_CONFIG = Path(__file__).resolve().parent / "default.yaml"


def _default_path() -> Path:
    env = os.environ.get("TOKENOPS_CONFIG")
    if env:
        return Path(env)
    return DEFAULT_CONFIG


def load_governance_yaml(path: Path | str | None = None) -> dict:
    """Return the ``governance:`` block from the config YAML (budgets + policies)."""
    config_path = Path(path) if path else _default_path()
    if not config_path.exists():
        return {}
    data = yaml.safe_load(config_path.read_text()) or {}
    block = data.get("governance")
    return block if isinstance(block, dict) else {}
