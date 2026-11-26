"""Incremental reader for Claude Code session transcripts (JSONL).

Claude Code writes one line per content block, so one API response appears on several lines
that repeat the same ``message.id`` and usage. Summing every line over-counts (in a real
session: 4,441 assistant lines, 1,944 unique responses). We keep the *last* line per
``message.id``, which carries the final usage.

Subagent work is logged in ``<session dir>/subagents/*.jsonl`` next to the main transcript and
is billed too, so it is read the same way.

The reader is incremental: it remembers a byte offset per file and only parses new complete
lines, so a hook stays fast on long sessions.
"""

from __future__ import annotations

import glob
import json
import os
from dataclasses import dataclass, field


@dataclass
class Response:
    model: str
    usage: dict
    speed: str | None
    sidechain: bool
    ts: str | None = None


@dataclass
class TranscriptState:
    offsets: dict[str, int] = field(default_factory=dict)
    responses: dict[str, Response] = field(default_factory=dict)


_KEEP = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
    "cache_creation",
)


def transcript_files(transcript_path: str) -> list[str]:
    files = [transcript_path] if transcript_path and os.path.exists(transcript_path) else []
    if transcript_path:
        base = os.path.splitext(transcript_path)[0]
        files += sorted(glob.glob(os.path.join(base, "subagents", "*.jsonl")))
    return files


def update(state: TranscriptState, transcript_path: str) -> int:
    """Read new lines from the transcript and its subagent files. Returns new responses seen."""
    new = 0
    for path in transcript_files(transcript_path):
        start = state.offsets.get(path, 0)
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        if size < start:  # file replaced or truncated: read again from the top
            start = 0
        if size == start:
            continue
        with open(path, "rb") as f:
            f.seek(start)
            chunk = f.read()
        end = chunk.rfind(b"\n")
        if end < 0:
            continue  # no complete line yet
        for raw in chunk[: end + 1].splitlines():
            if not raw.strip():
                continue
            try:
                o = json.loads(raw)
            except ValueError:
                continue
            if o.get("type") != "assistant":
                continue
            msg = o.get("message") or {}
            mid = msg.get("id") or o.get("requestId") or o.get("uuid")
            usage = msg.get("usage")
            model = msg.get("model") or ""
            if not mid or not usage or model == "<synthetic>":
                continue
            if mid not in state.responses:
                new += 1
            state.responses[mid] = Response(
                model=model,
                usage={k: usage.get(k) for k in _KEEP if usage.get(k) is not None},
                speed=usage.get("speed"),
                sidechain=bool(o.get("isSidechain")) or path != transcript_path,
                ts=o.get("timestamp"),
            )
        state.offsets[path] = start + end + 1
    return new
