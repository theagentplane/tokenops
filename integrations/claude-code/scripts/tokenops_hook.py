"""Claude Code hook entry point: ``tokenops_hook.py <EventName>``, payload on stdin.

Fails open: any error prints nothing and exits 0, so TokenOps can never break a session.
``TOKENOPS_DEBUG=1`` logs errors to ``hook-errors.log`` in the plugin data folder.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main() -> None:
    event = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        from tokenops_cc import guard, rtk

        handlers = {
            "UserPromptSubmit": guard.check,
            "PreToolUse": rtk.pre_tool_use,
            "PostToolUse": rtk.post_tool_use,
        }
        if event in handlers:
            out = handlers[event](json.load(sys.stdin))
            if out:
                sys.stdout.write(json.dumps(out))
    except Exception as e:  # noqa: BLE001 - fail open
        if os.environ.get("TOKENOPS_DEBUG"):
            from tokenops_cc.settings import data_dir

            with open(data_dir() / "hook-errors.log", "a", encoding="utf-8") as f:
                f.write(f"{event}: {type(e).__name__}: {e}\n")


if __name__ == "__main__":
    main()
    sys.exit(0)
