from __future__ import annotations

import os
from pathlib import Path

import yaml

from tokenops.config.schema import AppConfig

PRESETS_DIR = Path(__file__).resolve().parent / "presets"
DEFAULT_CONFIG = Path(__file__).resolve().parent / "default.yaml"


def _default_path() -> Path:
    env = os.environ.get("TOKENOPS_CONFIG")
    if env:
        return Path(env)
    return DEFAULT_CONFIG


def load_config(path: Path | str | None = None) -> AppConfig:
    config_path = Path(path) if path else _default_path()
    if not config_path.exists():
        return AppConfig()
    data = yaml.safe_load(config_path.read_text()) or {}
    return AppConfig.from_dict(data)


def save_config(cfg: AppConfig, path: Path | str) -> None:
    Path(path).write_text(yaml.safe_dump(cfg.to_dict(), sort_keys=False))


def list_presets() -> list[Path]:
    if not PRESETS_DIR.exists():
        return []
    return sorted(PRESETS_DIR.glob("*.yaml"))
