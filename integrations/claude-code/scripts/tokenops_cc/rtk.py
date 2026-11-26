"""Smart RTK: compact shell output with RTK only where Claude does not need it verbatim.

RTK (rtk-ai/rtk) rewrites a shell command to its compact form (``git status`` -> ``rtk git
status``). TokenOps asks the installed ``rtk`` for that rewrite (``rtk rewrite``, the call RTK's
own hook makes) and applies it, except for:

* reads of a file (``cat``, ``head``, ``tail``, ``sed -n``, ``nl``) and ``git diff``/``git show``:
  Claude often edits next and needs the exact text;
* a test run right after a test run that failed: Claude needs the full failure.

RTK stays its own install (its engine is BSL 1.1; TokenOps never bundles it). When RTK's own
hook is installed, smart RTK stays off so a command is never rewritten twice.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess

from . import savers, settings

VERBATIM = re.compile(r"^\s*(cat|head|tail|less|nl|sed\s+-n|git\s+(diff|show))\b")
TEST = re.compile(r"\b(pytest|jest|vitest|go\s+test|cargo\s+test|npm\s+(run\s+)?test|tox)\b")
FAILED = re.compile(r"\b(\d+\s+failed|FAILED|FAIL:|Traceback|Error:)", re.IGNORECASE)


def rtk_command() -> list[str] | None:
    """How to run rtk: ``$TOKENOPS_RTK`` (for tests) or ``rtk`` on PATH."""
    custom = os.environ.get("TOKENOPS_RTK")
    if custom:
        return [part.strip('"') for part in shlex.split(custom, posix=False)]
    found = shutil.which("rtk")
    return [found] if found else None


def status() -> str:
    if rtk_command() is None:
        return "off (rtk not found; install it from github.com/rtk-ai/rtk to use it)"
    if "rtk" in savers.detect():
        return "off (RTK's own hook is installed; remove it from your Claude Code settings first)"
    return "on (compacts shell output, keeps file reads, diffs and failing tests verbatim)"


def rewrite(command: str, last_test_failed: bool) -> str | None:
    if VERBATIM.match(command) or (last_test_failed and TEST.search(command)):
        return None
    rtk = rtk_command()
    if rtk is None:
        return None
    try:
        r = subprocess.run([*rtk, "rewrite", command], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    new = r.stdout.strip()
    if r.returncode not in (0, 3) or not new or new == command.strip():
        return None  # 1: nothing to rewrite, 2: denied
    return new


def _active() -> bool:
    return bool(settings.load_config().get("autopilot")) and status().startswith("on")


def pre_tool_use(payload: dict) -> dict | None:
    """Rewrite a Bash command to its RTK form when that is safe."""
    tool_input = payload.get("tool_input") or {}
    command = str(tool_input.get("command") or "")
    sid = payload.get("session_id") or "unknown"
    if payload.get("tool_name") != "Bash" or not command or not _active():
        return None
    if settings.load_session(sid).get("arms", {}).get("rtk") is False:
        return None  # the A/B test has RTK off in this session
    new = rewrite(command, settings.load_session(sid).get("last_test_failed", False))
    if new is None:
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "updatedInput": {**tool_input, "command": new},
        }
    }


def post_tool_use(payload: dict) -> None:
    """Remember whether the last test run failed, so the next one is shown in full."""
    command = str((payload.get("tool_input") or {}).get("command") or "")
    if payload.get("tool_name") != "Bash" or not TEST.search(command):
        return None
    sid = payload.get("session_id") or "unknown"
    state = settings.load_session(sid)
    state["last_test_failed"] = bool(FAILED.search(str(payload.get("tool_response") or "")))
    settings.save_session(sid, state)
    return None
