"""Claude Code plugin: caveman adapter and the saver A/B test."""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "integrations" / "claude-code" / "scripts"))

from tokenops_cc import ab, caveman, rtk, settings  # noqa: E402

FAKE = pathlib.Path(__file__).with_name("fake_rtk.py")


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    claude = tmp_path / "claude"
    skill = claude / "plugins" / "cache" / "caveman" / "caveman" / "4.2.0" / "skills" / "caveman"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: caveman\n---\n\nRespond terse like smart caveman.")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude))
    monkeypatch.setenv("TOKENOPS_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("CAVEMAN_DEFAULT_MODE", "off")
    monkeypatch.setenv("TOKENOPS_RTK", f'"{sys.executable}" "{FAKE}"')
    settings.save_config({"saver": True})
    return tmp_path


def test_caveman_needs_its_own_default_off_to_be_tested(monkeypatch):
    assert caveman.status() == "testable"
    assert caveman.rules() == "Respond terse like smart caveman."
    monkeypatch.delenv("CAVEMAN_DEFAULT_MODE")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/nonexistent")
    assert caveman.status().startswith("off (set caveman's default to off")


def test_session_start_picks_arms_once_and_loads_caveman_only_when_on(monkeypatch):
    monkeypatch.setattr(ab.random, "random", lambda: 0.1)  # both on
    out = ab.session_start({"session_id": "s1", "transcript_path": "t.jsonl", "source": "startup"})
    assert "smart caveman" in out["hookSpecificOutput"]["additionalContext"]
    assert settings.load_session("s1")["arms"] == {"caveman": True, "rtk": True}
    monkeypatch.setattr(ab.random, "random", lambda: 0.9)  # resume keeps the first choice
    assert ab.session_start({"session_id": "s1", "source": "resume"}) is not None
    assert ab.session_start({"session_id": "s2"}) is None  # both off
    bash = {"session_id": "s2", "tool_name": "Bash", "tool_input": {"command": "git status"}}
    assert rtk.pre_tool_use(bash) is None  # RTK off in this session


def _session(env, sid, arms, cost_per_prompt):
    path = env / f"{sid}.jsonl"
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0}
    usage["input_tokens"] = round(cost_per_prompt * 2 / 4.0 * 1e6)  # 2 prompts, $4 per M input
    lines = [
        {"type": "user", "message": {"role": "user", "content": "fix the bug"}},
        {"type": "user", "message": {"role": "user", "content": "and the test"}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}},
        {"type": "assistant", "message": {"id": sid, "model": "claude-opus-5-5", "usage": usage}},
    ]
    path.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    settings.save_session(sid, {"arms": arms, "transcript_path": str(path)})


def test_results_keep_a_saver_that_saves_and_keep_testing_an_unclear_one(env):
    for i in range(10):
        _session(env, f"on{i}", {"rtk": True, "caveman": i % 2 == 0}, 0.80 + 0.01 * i)
        _session(env, f"off{i}", {"rtk": False, "caveman": i % 2 == 1}, 1.00 + 0.01 * i)
    rows = ab.results()
    assert rows["rtk"]["verdict"] == "on" and rows["rtk"]["change"] == pytest.approx(
        -0.19, abs=0.01
    )
    # caveman: no difference, but the range still allows a 10% saving, so it keeps testing
    assert rows["caveman"]["verdict"] == "testing" and abs(rows["caveman"]["change"]) < 0.01
    assert settings.load_config()["decisions"] == {"rtk": "on"}
    assert "kept on" in ab.render(rows) and "still testing" in ab.render(rows)
    assert ab.usage_per_prompt(str(env / "on0.jsonl")) == pytest.approx(0.80)
