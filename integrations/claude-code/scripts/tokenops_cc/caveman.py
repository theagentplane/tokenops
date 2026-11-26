"""caveman adapter: load caveman's own rules in the sessions where the A/B test turns it on.

caveman (JuliusBrussee/caveman) stays its own install. TokenOps reads the installed skill file
and adds it at session start, so it can turn caveman on in some sessions and off in others. For
that, caveman's own default must be off (``CAVEMAN_DEFAULT_MODE=off``, or ``"defaultMode": "off"``
in caveman's config file); otherwise caveman is on everywhere and there is nothing to compare.
"""

from __future__ import annotations

import glob
import json
import os
from pathlib import Path


def _claude_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def skill_file() -> Path | None:
    """The installed caveman skill, newest first."""
    pattern = str(_claude_dir() / "plugins" / "**" / "skills" / "caveman" / "SKILL.md")
    found = [Path(p) for p in glob.glob(pattern, recursive=True) if "caveman" in p]
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


def _config_path() -> Path:
    if os.environ.get("XDG_CONFIG_HOME"):
        return Path(os.environ["XDG_CONFIG_HOME"]) / "caveman" / "config.json"
    if os.name == "nt":
        return (
            Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
            / "caveman"
            / "config.json"
        )
    return Path.home() / ".config" / "caveman" / "config.json"


def default_off() -> bool:
    if os.environ.get("CAVEMAN_DEFAULT_MODE", "").lower() == "off":
        return True
    try:
        config = json.loads(_config_path().read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return False
    return str(config.get("defaultMode", "")).lower() == "off"


def status() -> str:
    if skill_file() is None:
        return "off (caveman not installed)"
    if not default_off():
        return (
            f'off (set caveman\'s default to off first: "defaultMode": "off" in {_config_path()})'
        )
    return "testable"


def rules() -> str:
    """caveman's skill text without its front matter, as the skill would load it."""
    path = skill_file()
    text = path.read_text(encoding="utf-8") if path else ""
    if text.startswith("---"):
        text = text.split("---", 2)[2]
    return text.strip()
