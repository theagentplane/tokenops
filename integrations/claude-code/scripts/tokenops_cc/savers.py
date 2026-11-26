"""Detect which token savers are active, so sessions can be compared with and without them.

Read-only: looks at Claude Code settings files, never changes them.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

KNOWN = {
    "caveman": ("caveman",),
    "rtk": ("rtk ", "rtk-", "/rtk", "rtk.exe", "rtk hook", "rtk rewrite"),
    "headroom": ("headroom",),
    "context-mode": ("context-mode", "context_mode"),
    "claude-mem": ("claude-mem",),
    "ponytail": ("ponytail",),
}


def _read(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _settings_files(cwd: str | None) -> list[Path]:
    home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    files = [home / "settings.json", home / "settings.local.json"]
    if cwd:
        files += [
            Path(cwd) / ".claude" / "settings.json",
            Path(cwd) / ".claude" / "settings.local.json",
        ]
    return files


def detect(cwd: str | None = None) -> list[str]:
    blob = ""
    for f in _settings_files(cwd):
        s = _read(f)
        if not s:
            continue
        enabled = s.get("enabledPlugins") or {}
        if isinstance(enabled, dict):
            blob += " ".join(k for k, v in enabled.items() if v) + " "
        elif isinstance(enabled, list):
            blob += " ".join(map(str, enabled)) + " "
        blob += json.dumps(s.get("hooks") or {}) + " " + json.dumps(s.get("mcpServers") or {}) + " "
    blob = blob.lower()
    return sorted(name for name, needles in KNOWN.items() if any(n in blob for n in needles))
