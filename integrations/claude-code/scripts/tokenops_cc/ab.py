"""Saver A/B: turn each saver on in a random half of sessions and keep it only if it saves.

At session start, every saver that can be tested (caveman, smart RTK) is switched on or off at
random and the choice is stored with the session. Comparing usage per prompt between the two
halves, after at least ``MIN_SESSIONS`` sessions in each, gives the saver's measured effect on
this user's own work. A saver is kept on when the whole 95% range is a saving, turned off when
it cannot save 5% or more, and tested further otherwise. Hooks cannot see task quality, so this
measures usage only.
"""

from __future__ import annotations

import json
import os
import random

from . import caveman, rtk, settings
from .cost import breakdown
from .transcript import TranscriptState, update

MIN_SESSIONS = 10
SAVERS = ("caveman", "rtk")
NAMES = {"caveman": "caveman", "rtk": "Smart RTK"}


def testable() -> dict[str, bool]:
    return {"caveman": caveman.status() == "testable", "rtk": rtk.status().startswith("on")}


def session_start(payload: dict) -> dict | None:
    """Pick this session's arms (kept on resume and compaction); load caveman when it is on."""
    config = settings.load_config()
    if not config.get("saver"):
        return None
    sid = payload.get("session_id") or "unknown"
    state = settings.load_session(sid)
    if "arms" not in state:
        decided = config.get("decisions", {})
        state["arms"] = {
            saver: decided[saver] == "on" if saver in decided else random.random() < 0.5
            for saver, ok in testable().items()
            if ok
        }
        state["transcript_path"] = payload.get("transcript_path") or ""
        settings.save_session(sid, state)
    if not state["arms"].get("caveman"):
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": caveman.rules()[:9500],
        }
    }


def _prompts(path: str) -> int:
    """Messages the user typed (not tool results, slash-command output or reminders)."""
    n = 0
    with open(path, encoding="utf-8", errors="ignore") as f:
        for raw in f:
            if '"user"' not in raw:
                continue
            try:
                o = json.loads(raw)
            except ValueError:
                continue
            content = (o.get("message") or {}).get("content")
            is_typed = isinstance(content, str) and not content.startswith("<")
            if o.get("type") == "user" and is_typed and not o.get("isMeta"):
                n += 1
    return n


def usage_per_prompt(path: str) -> float | None:
    if not path or not os.path.exists(path):
        return None
    prompts = _prompts(path)
    if prompts == 0:
        return None
    state = TranscriptState()
    update(state, path)
    return breakdown(state.responses.values())["cost_usd"] / prompts


def _ratio_range(on: list[float], off: list[float], draws: int = 2000) -> tuple[float, float]:
    """95% bootstrap range of mean(on) / mean(off)."""
    rng = random.Random(0)
    ratios = []
    for _ in range(draws):
        a = [rng.choice(on) for _ in on]
        b = [rng.choice(off) for _ in off]
        ratios.append((sum(a) / len(a)) / (sum(b) / len(b)))
    ratios.sort()
    return ratios[int(0.025 * draws)], ratios[int(0.975 * draws) - 1]


def results() -> dict[str, dict]:
    """Per saver: sessions on and off, measured change and verdict. Saves decisions to config."""
    groups: dict[str, dict[bool, list[float]]] = {s: {True: [], False: []} for s in SAVERS}
    for state in settings.all_sessions():
        if not state.get("arms"):
            continue
        value = usage_per_prompt(state.get("transcript_path", ""))
        if not value:
            continue
        for saver, on in state["arms"].items():
            groups[saver][on].append(value)
    config = settings.load_config()
    out: dict[str, dict] = {}
    for saver, g in groups.items():
        on, off = g[True], g[False]
        if not on and not off:
            continue
        row: dict = {"on": len(on), "off": len(off), "verdict": "testing"}
        if min(len(on), len(off)) >= MIN_SESSIONS:
            ratio = (sum(on) / len(on)) / (sum(off) / len(off))
            lo, hi = _ratio_range(on, off)
            row.update(change=ratio - 1, low=lo - 1, high=hi - 1)
            if hi < 1:
                row["verdict"] = "on"
            elif lo > 0.95:
                row["verdict"] = "off"
            if row["verdict"] != "testing":
                config.setdefault("decisions", {})[saver] = row["verdict"]
        out[saver] = row
    settings.save_config(config)
    return out


def render(rows: dict[str, dict]) -> str:
    if not rows:
        return ""
    lines = ["", "Measured on your sessions (saver mode A/B, usage per prompt)"]
    for saver, r in rows.items():
        if "change" not in r:
            lines.append(
                f"  {NAMES[saver]:10s} testing: {r['on']} sessions on, {r['off']} off "
                f"(decides at {MIN_SESSIONS} each)"
            )
            continue
        verdict = {"on": "kept on", "off": "turned off", "testing": "still testing"}[r["verdict"]]
        lines.append(
            f"  {NAMES[saver]:10s} {100 * r['change']:+.0f}% usage per prompt "
            f"(95% range {100 * r['low']:+.0f}% to {100 * r['high']:+.0f}%) -> {verdict}"
        )
    lines.append("  Usage only: hooks cannot see whether the work went as well.")
    return "\n".join(lines)
