"""Claude Code plugin: transcript reading, pricing and /tokenops:doctor."""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "integrations" / "claude-code" / "scripts"))

from tokenops_cc.cost import breakdown  # noqa: E402
from tokenops_cc.doctor import diagnose, render  # noqa: E402
from tokenops_cc.prices import price_for, usage_cost  # noqa: E402
from tokenops_cc.transcript import TranscriptState, update  # noqa: E402


def _assistant(mid, ts="2026-11-26T10:00:00Z", out=100, w1h=0, model="claude-opus-5-5"):
    usage = {
        "input_tokens": 10,
        "output_tokens": out,
        "cache_read_input_tokens": 1000,
        "cache_creation_input_tokens": w1h,
        "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": w1h},
    }
    return {
        "type": "assistant",
        "timestamp": ts,
        "version": "2.1.320",
        "message": {"id": mid, "model": model, "usage": usage},
    }


def _write(path: pathlib.Path, lines: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")


def test_prices_match_the_framework_price_book():
    spec = importlib.util.spec_from_file_location(
        "sync", ROOT / "scripts" / "sync-claude-prices.py"
    )
    sync = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync)
    assert sync.TARGET.read_text(encoding="utf-8") == sync.rendered(), (
        "prices.json is stale: run python scripts/sync-claude-prices.py"
    )


def test_cost_of_cache_writes_and_unknown_models():
    one_hour = {"cache_creation_input_tokens": 1_000_000}
    one_hour["cache_creation"] = {"ephemeral_1h_input_tokens": 1_000_000}
    assert usage_cost("claude-opus-5-5", one_hour)[0] == pytest.approx(8.0)  # 2x $4 input
    assert usage_cost("claude-opus-5-5", {"cache_creation_input_tokens": 1_000_000})[0] == (
        pytest.approx(5.0)  # untyped writes count as 5-minute: 1.25x
    )
    assert price_for("claude-haiku-4-5-20251001")[1]
    assert not price_for("some-future-model")[1]


def test_reader_keeps_last_line_per_response_and_reads_subagents(tmp_path):
    main = tmp_path / "s.jsonl"
    _write(main, [_assistant("m1", out=50), _assistant("m1", out=120), _assistant("m2")])
    _write(tmp_path / "s" / "subagents" / "a.jsonl", [_assistant("m3", model="claude-haiku-5-5")])
    state = TranscriptState()
    assert update(state, str(main)) == 3
    assert state.responses["m1"].usage["output_tokens"] == 120
    assert breakdown(state.responses.values())["subagent_responses"] == 1
    with main.open("a", encoding="utf-8") as f:
        f.write('{"type": "assistant", "message": {"id": "m4"')  # half-written line
    assert update(state, str(main)) == 0


def test_doctor_prices_rebuys_after_breaks(tmp_path):
    _write(
        tmp_path / "p" / "s.jsonl",
        [
            _assistant("m1", "2026-11-26T10:00:00Z", w1h=30_000),
            _assistant("m2", "2026-11-26T10:01:00Z"),
            _assistant("m3", "2026-11-26T12:30:00Z", w1h=200_000),  # back after 2.5 h
            _assistant("m4", "2026-11-26T12:31:00Z"),
        ],
    )
    d = diagnose(str(tmp_path), days=36500)
    assert (d.sessions, d.rebuys) == (1, 1)
    assert d.rebuy_usd == pytest.approx(200_000 * 4.0 * 2.0 / 1e6)
    text = render(d)
    assert "Re-buying context after breaks" in text and "/compact" in text
