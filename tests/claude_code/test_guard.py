"""Claude Code plugin: autopilot switch and the resume guard."""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "integrations" / "claude-code" / "scripts"
sys.path.insert(0, str(PLUGIN))

from tokenops_cc import guard, settings  # noqa: E402


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKENOPS_DATA", str(tmp_path / "data"))
    settings.save_config({"autopilot": True})


def _transcript(tmp_path, ts="2026-11-26T10:00:00Z", context=200_000, five_min=False):
    write = {"ephemeral_5m_input_tokens": 1000} if five_min else {"ephemeral_1h_input_tokens": 1000}
    line = {
        "type": "assistant",
        "timestamp": ts,
        "message": {
            "id": "m1",
            "model": "claude-opus-5-5",
            "usage": {
                "input_tokens": 10,
                "cache_read_input_tokens": context - 1010,
                "cache_creation_input_tokens": 1000,
                "cache_creation": write,
            },
        },
    }
    path = tmp_path / "s.jsonl"
    path.write_text(json.dumps(line) + "\n", encoding="utf-8")
    return {"session_id": "s1", "transcript_path": str(path), "prompt": "hi"}


T0 = 1795687200.0  # 2026-11-26T10:00:00Z


def test_holds_the_first_message_after_the_cache_expired_then_lets_it_through(tmp_path):
    payload = _transcript(tmp_path)
    out = guard.check(payload, now=T0 + 2 * 3600)
    assert out["decision"] == "block"
    assert "$1.60" in out["reason"]  # 200k tokens x $4/M x 2 (1-hour cache write)
    assert guard.check(payload, now=T0 + 2 * 3600 + 30) is None  # sent again: allowed


def test_lets_messages_through_while_the_cache_is_warm_or_the_context_is_small(tmp_path):
    assert guard.check(_transcript(tmp_path), now=T0 + 30 * 60) is None
    assert guard.check(_transcript(tmp_path, context=20_000), now=T0 + 5 * 3600) is None


def test_five_minute_cache_expires_after_five_minutes(tmp_path):
    out = guard.check(_transcript(tmp_path, five_min=True), now=T0 + 10 * 60)
    assert out and "10 min" in out["reason"]


def test_does_nothing_when_autopilot_is_off(tmp_path):
    settings.save_config({"autopilot": False})
    assert guard.check(_transcript(tmp_path), now=T0 + 5 * 3600) is None


def test_hook_fails_open_on_bad_input():
    r = subprocess.run(
        [sys.executable, str(PLUGIN / "tokenops_hook.py"), "UserPromptSubmit"],
        input="not json",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert (r.returncode, r.stdout) == (0, "")
