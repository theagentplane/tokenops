"""Local settings and per-session state, in Claude Code's plugin data folder.

``$CLAUDE_PLUGIN_DATA`` when Claude Code provides it, else ``~/.tokenops/claude-code``. Nothing
here leaves the machine.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path


def data_dir() -> Path:
    d = os.environ.get("TOKENOPS_DATA") or os.environ.get("CLAUDE_PLUGIN_DATA")
    path = Path(d) if d else Path.home() / ".tokenops" / "claude-code"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def load_config() -> dict:
    return _read(data_dir() / "config.json")


def save_config(config: dict) -> None:
    _write(data_dir() / "config.json", config)


def _session_path(session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "unknown")[:128]
    (data_dir() / "sessions").mkdir(exist_ok=True)
    return data_dir() / "sessions" / f"{safe}.json"


def load_session(session_id: str) -> dict:
    return _read(_session_path(session_id))


def save_session(session_id: str, state: dict) -> None:
    _write(_session_path(session_id), state)
