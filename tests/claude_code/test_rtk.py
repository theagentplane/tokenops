"""Claude Code plugin: smart RTK."""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "integrations" / "claude-code" / "scripts"))

from tokenops_cc import rtk, settings  # noqa: E402

FAKE = pathlib.Path(__file__).with_name("fake_rtk.py")


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKENOPS_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))  # no RTK hook installed
    monkeypatch.setenv("TOKENOPS_RTK", f'"{sys.executable}" "{FAKE}"')
    settings.save_config({"saver": True})


def _bash(command, **extra):
    return {"session_id": "s1", "tool_name": "Bash", "tool_input": {"command": command, **extra}}


def test_rewrites_commands_rtk_compacts_and_keeps_the_other_input_fields():
    out = rtk.pre_tool_use(_bash("git status", timeout=1000))
    assert out["hookSpecificOutput"]["updatedInput"] == {
        "command": "rtk git status",
        "timeout": 1000,
    }


def test_keeps_file_reads_diffs_and_unknown_commands_verbatim():
    for command in ("cat setup.py", "head -50 a.py", "sed -n 1,20p a.py", "git diff", "echo hi"):
        assert rtk.pre_tool_use(_bash(command)) is None


def test_shows_the_next_test_run_in_full_after_a_failure():
    assert rtk.pre_tool_use(_bash("pytest -x")) is not None
    rtk.post_tool_use({**_bash("pytest -x"), "tool_response": {"stdout": "1 failed, 3 passed"}})
    assert rtk.pre_tool_use(_bash("pytest -x")) is None
    rtk.post_tool_use({**_bash("pytest -x"), "tool_response": {"stdout": "4 passed"}})
    assert rtk.pre_tool_use(_bash("pytest -x")) is not None


def test_stays_off_when_saver_mode_is_off_rtk_is_missing_or_rtk_has_its_own_hook(
    tmp_path, monkeypatch
):
    settings.save_config({"saver": False})
    assert rtk.pre_tool_use(_bash("git status")) is None
    settings.save_config({"saver": True})
    monkeypatch.setenv("TOKENOPS_RTK", "")
    monkeypatch.setenv("PATH", "")
    assert rtk.pre_tool_use(_bash("git status")) is None
    assert rtk.status().startswith("off (rtk not found")
    monkeypatch.setenv("TOKENOPS_RTK", f'"{sys.executable}" "{FAKE}"')
    hooks = tmp_path / "claude" / "settings.json"
    hooks.parent.mkdir(parents=True, exist_ok=True)
    hooks.write_text('{"hooks": {"PreToolUse": [{"command": "rtk hook claude"}]}}')
    assert rtk.status().startswith("off (RTK's own hook")
    assert rtk.pre_tool_use(_bash("git status")) is None
