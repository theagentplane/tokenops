"""Resume guard: hold the first message to a session whose prompt cache has expired.

After a break longer than the cache lifetime (1 hour on Claude plans, 5 minutes on an API key by
default), the next message writes the whole conversation to the cache again, at 2x (1 hour) or
1.25x (5 minutes) the input price. The guard holds that message once, says what it will cost and
offers cheaper ways on. Sending it again goes through, so it never traps anyone.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import time

from . import settings
from .prices import CACHE_WRITE_1H, CACHE_WRITE_5M, price_for

TAIL_BYTES = 4_000_000
MIN_CONTEXT_TOKENS = int(os.environ.get("TOKENOPS_GUARD_MIN_TOKENS", "50000"))


def last_response(transcript_path: str) -> dict | None:
    """The newest main-thread response: timestamp, model, context size, cache lifetime."""
    try:
        with open(transcript_path, "rb") as f:
            f.seek(max(0, os.path.getsize(transcript_path) - TAIL_BYTES))
            lines = f.read().splitlines()
    except OSError:
        return None
    for raw in reversed(lines):
        try:
            o = json.loads(raw)
        except ValueError:
            continue
        msg = o.get("message") or {}
        usage = msg.get("usage")
        if o.get("type") != "assistant" or o.get("isSidechain") or not usage:
            continue
        if msg.get("model") == "<synthetic>":
            continue
        cc = usage.get("cache_creation") or {}
        context = sum(
            usage.get(k) or 0
            for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
        )
        try:
            ts = dt.datetime.fromisoformat(o["timestamp"].replace("Z", "+00:00")).timestamp()
        except (KeyError, ValueError):
            return None
        # The cache this session writes to: 5 minutes only when the last write was a 5m write.
        five_min = (cc.get("ephemeral_5m_input_tokens") or 0) > 0 and not cc.get(
            "ephemeral_1h_input_tokens"
        )
        ttl = 300 if five_min else 3600
        return {"ts": ts, "model": msg.get("model", ""), "context": context, "ttl": ttl}
    return None


def check(payload: dict, now: float | None = None) -> dict | None:
    """UserPromptSubmit handler. Returns a block decision, or None to let the prompt through."""
    if not settings.load_config().get("autopilot"):
        return None
    last = last_response(payload.get("transcript_path") or "")
    now = time.time() if now is None else now
    if not last or last["context"] < MIN_CONTEXT_TOKENS or now - last["ts"] <= last["ttl"]:
        return None
    sid = payload.get("session_id") or "unknown"
    state = settings.load_session(sid)
    if state.get("guard_warned_for") == last["ts"]:
        return None  # second send: the user chose to go on
    state["guard_warned_for"] = last["ts"]
    settings.save_session(sid, state)

    p, _ = price_for(last["model"])
    write = CACHE_WRITE_1H if last["ttl"] == 3600 else CACHE_WRITE_5M
    cold = last["context"] * p["input"] * write / 1e6
    warm = last["context"] * p["cache_read"] / 1e6
    hours = (now - last["ts"]) / 3600
    away = f"{hours:.1f} h" if hours >= 1 else f"{(now - last['ts']) / 60:.0f} min"
    return {
        "decision": "block",
        "reason": (
            f"TokenOps: this session's cache expired ({away} since the last reply). Sending now "
            f"re-reads {last['context'] / 1000:,.0f}k tokens at the cache-write price: about "
            f"${cold:.2f} API-equivalent, against ${warm:.2f} while the cache was warm.\n"
            "  - Send the same message again to continue anyway.\n"
            "  - Or run /compact first: it keeps the gist in far fewer tokens.\n"
            "  - Or /clear and paste a 3-line summary of where you were (cheapest)."
        ),
    }
