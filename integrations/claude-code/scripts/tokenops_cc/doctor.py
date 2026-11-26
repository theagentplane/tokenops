"""Why am I hitting my limit? Where your Claude Code usage goes, and what to change.

Read from your own transcripts, nothing estimated from benchmarks:

* **Re-buying context after a break.** Claude Code caches the conversation. Once the cache
  expires (1 hour on Claude plans, 5 minutes on an API key by default), the next message writes
  the whole context again, at 1.25x (5 min) or 2x (1 hour) the input price.
* **Re-reading context.** Every turn reads the cached conversation again. Cheap per token, large
  in total for long sessions.
* **Output, and shell output.** What output-style tools (caveman) and shell-output tools (RTK)
  can shrink at most.

Usage is priced at Anthropic API list rates, so every row is comparable. On a Claude plan it is
the share of your limit, not a bill.
"""

from __future__ import annotations

import datetime as dt
import glob
import json
import os
import re
import time
from dataclasses import dataclass

from . import savers
from .cost import breakdown
from .prices import CACHE_WRITE_1H, CACHE_WRITE_5M, price_for, write_tokens
from .transcript import TranscriptState, update

BREAK_S = 3600  # a gap longer than the 1-hour cache
REBUY_TOKENS = 20_000  # a cache write this large after a break is a re-buy, not growth
IDLE_COMPACTION = (2, 1, 299)  # Claude Code compacts idle sessions before the cache expires
RTK_CMD = re.compile(
    r"^\s*(git|ls|cat|head|tail|grep|rg|find|tree|wc|pytest|python3? -m pytest|npm|npx|pnpm|yarn|"
    r"bun|cargo|go (test|build)|tsc|eslint|jest|vitest|make|docker|kubectl|curl)\b"
)


@dataclass
class Diagnosis:
    days: int
    sessions: int
    cost: dict  # cost.breakdown() over all responses
    rebuy_usd: float
    rebuys: int
    worst_rebuy_usd: float
    cache_writes_5m: int
    cache_writes_1h: int
    tool_chars: int
    rtk_chars: int
    version: tuple[int, ...] | None
    active_savers: list[str]


def _epoch(ts: str | None) -> float | None:
    try:
        return dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() if ts else None
    except ValueError:
        return None


def _write_usd(model: str, usage: dict) -> float:
    w5m, w1h = write_tokens(usage)
    return (w5m * CACHE_WRITE_5M + w1h * CACHE_WRITE_1H) * price_for(model)[0]["input"] / 1e6


def _scan_tools(path: str) -> tuple[int, int, tuple[int, ...] | None]:
    """Tool output chars, the part from RTK-compactable shell commands, newest Claude Code version."""
    bash: dict[str, str] = {}
    total = rtk = 0
    version = None
    with open(path, encoding="utf-8", errors="ignore") as f:
        for raw in f:
            try:
                o = json.loads(raw)
            except ValueError:
                continue
            m = re.match(r"(\d+)\.(\d+)\.(\d+)", o.get("version") or "")
            if m:
                version = max(version or (0,), tuple(int(x) for x in m.groups()))
            content = (o.get("message") or {}).get("content")
            for b in content if isinstance(content, list) else []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use" and b.get("name") == "Bash":
                    bash[b.get("id", "")] = str((b.get("input") or {}).get("command", ""))
                elif b.get("type") == "tool_result":
                    c = b.get("content")
                    n = (
                        len(c)
                        if isinstance(c, str)
                        else sum(len(x.get("text", "")) for x in c or [] if isinstance(x, dict))
                    )
                    total += n
                    if RTK_CMD.match(bash.get(b.get("tool_use_id", ""), "")):
                        rtk += n
    return total, rtk, version


def diagnose(projects_dir: str, days: int = 30, cwd: str | None = None) -> Diagnosis:
    cutoff = time.time() - days * 86400
    responses = []
    sessions = rebuys = tool_chars = rtk_chars = w5 = w1 = 0
    rebuy_usd = worst = 0.0
    version = None
    for path in glob.glob(os.path.join(projects_dir, "*", "*.jsonl")):
        if os.path.getmtime(path) < cutoff:
            continue
        ts = TranscriptState()
        update(ts, path)
        if len(ts.responses) < 3:
            continue
        sessions += 1
        responses += ts.responses.values()
        main = sorted(
            (r for r in ts.responses.values() if not r.sidechain), key=lambda r: r.ts or ""
        )
        prev = None
        for r in main:
            a, b = write_tokens(r.usage)
            w5 += a
            w1 += b
            t = _epoch(r.ts)
            if (
                prev
                and t
                and t - prev > BREAK_S
                and (r.usage.get("cache_creation_input_tokens") or 0) >= REBUY_TOKENS
            ):
                usd = _write_usd(r.model, r.usage)
                rebuy_usd += usd
                rebuys += 1
                worst = max(worst, usd)
            prev = t or prev
        n, k, v = _scan_tools(path)
        tool_chars += n
        rtk_chars += k
        if v and (version is None or v > version):
            version = v
    return Diagnosis(
        days,
        sessions,
        breakdown(responses),
        rebuy_usd,
        rebuys,
        worst,
        w5,
        w1,
        tool_chars,
        rtk_chars,
        version,
        savers.detect(cwd),
    )


def render(d: Diagnosis) -> str:
    c = d.cost
    total = c["cost_usd"]
    if total <= 0:
        return f"No Claude Code usage found in the last {d.days} days."

    def pct(x: float) -> str:
        return f"{100 * x / total:3.0f}%"

    growth = max(0.0, c["cost_cache_write"] - d.rebuy_usd)
    rows = [
        ("Re-buying context after breaks", d.rebuy_usd),
        ("Re-reading context every turn", c["cost_cache_read"]),
        ("Caching new context", growth),
        ("Claude's output", c["cost_output"]),
        ("Uncached input", c["cost_input"]),
    ]
    out = [
        f"Why am I hitting my limit?   (last {d.days} days, {d.sessions} sessions, "
        f"${total:,.0f} at API list prices)",
        "",
        "Where your usage goes",
    ]
    out += [f"  {pct(v)}  {name}" for name, v in sorted(rows, key=lambda x: -x[1])]
    sub = c["subagent_responses"]
    if sub:
        out.append(f"        ({sub} of {c['responses']} responses came from subagents)")

    fixes = []
    if d.rebuy_usd / total >= 0.05:
        how = (
            "Update Claude Code: v2.1.299+ compacts idle sessions before the cache expires."
            if d.version and d.version < IDLE_COMPACTION
            else "Run /compact before a long break, or start fresh with a short summary when you return."
        )
        fixes.append(
            f"Breaks cost you {pct(d.rebuy_usd).strip()}: {d.rebuys} times you came back to an "
            f"expired cache (worst: ${d.worst_rebuy_usd:.2f} for one message). {how}"
        )
    if c["cost_cache_read"] / total >= 0.3:
        fixes.append(
            f"Re-reading is {pct(c['cost_cache_read']).strip()}: every turn reads the whole "
            "conversation again, so long sessions get more expensive per message. Use /clear "
            "when you switch to an unrelated task."
        )
    if d.cache_writes_5m > d.cache_writes_1h:
        fixes.append(
            "Your cache expires after 5 minutes (API-key default), so short pauses re-buy "
            'context too. Set "promptCacheTtl": "1h" in ~/.claude/settings.json.'
        )
    out_share = c["cost_output"] / total
    caveman = "caveman" in d.active_savers
    fixes.append(
        f"Output is {100 * out_share:.0f}% of your usage, so a terse-output tool like caveman can "
        f"save at most that{' (and about 8.5% of it in practice)' if out_share else ''}. "
        + (
            "Keep it for readability, not for your limit."
            if caveman and out_share < 0.2
            else "Not worth installing for your limit."
            if out_share < 0.2
            else "Worth a test."
        )
    )
    if d.tool_chars:
        share = d.rtk_chars / d.tool_chars
        rtk = "rtk" in d.active_savers
        fixes.append(
            f"{100 * share:.0f}% of the tool output Claude read came from shell commands RTK can "
            "compact (Read and Grep bypass it). "
            + (
                "Small: RTK can't move your limit much."
                if share < 0.2
                else "Large enough that RTK may help: test it."
                if not rtk
                else "RTK fits your work."
            )
        )
    out += ["", "What to change"] + [f"  {i}. {f}" for i, f in enumerate(fixes, 1)]
    out += [
        "",
        f'Share: "{pct(d.rebuy_usd).strip()} of my Claude Code usage went to re-buying context '
        'after breaks. Why are you hitting your limit? /tokenops:doctor"',
    ]
    return "\n".join(out)
