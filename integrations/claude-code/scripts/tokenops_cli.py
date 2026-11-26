"""TokenOps for Claude Code, command line. The plugin's slash commands call it through bin/tokenops.

tokenops doctor [--days N]    Why am I hitting my limit?
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tokenops_cc import settings  # noqa: E402
from tokenops_cc.doctor import diagnose, render  # noqa: E402


def projects_dir() -> str:
    home = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    return os.path.join(home, "projects")


def saver_mode(action: str) -> str:
    config = settings.load_config()
    if action in ("on", "off"):
        config["saver"] = action == "on"
        settings.save_config(config)
    if not config.get("saver"):
        return "Saver mode is off. Turn it on with /tokenops:saver on"
    return (
        "Saver mode is on.\n"
        "  Resume guard: on (holds the first message after the cache expires, once)\n"
        "Turn it off with /tokenops:saver off"
    )


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="tokenops")
    sub = ap.add_subparsers(dest="cmd", required=True)
    doctor = sub.add_parser("doctor", help="why am I hitting my limit?")
    doctor.add_argument("--days", type=int, default=30)
    saver = sub.add_parser("saver", help="on, off or status")
    saver.add_argument("action", nargs="?", default="status", choices=["on", "off", "status"])
    a = ap.parse_args(argv)
    if a.cmd == "saver":
        print(saver_mode(a.action))
    else:
        print(render(diagnose(projects_dir(), a.days, os.getcwd())))


if __name__ == "__main__":
    main()
