#!/usr/bin/env python3
"""Copy the canonical skill to the editor-specific skill directories.

Claude Code reads .claude/skills/, Cursor reads .cursor/skills/. The content is
identical, so .claude/ is the source of truth and the rest are generated. Run
``make sync-skills`` after editing the canonical file; CI checks they match.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE = ROOT / ".claude" / "skills" / "integrate-tokenops" / "SKILL.md"
TARGETS = [ROOT / ".cursor" / "skills" / "integrate-tokenops" / "SKILL.md"]

NOTE = (
    "<!-- Generated from .claude/skills/integrate-tokenops/SKILL.md by "
    "`make sync-skills`. Edit that file, not this one. -->\n\n"
)


def rendered() -> str:
    text = SOURCE.read_text(encoding="utf-8")
    # The note must sit after the YAML frontmatter, which has to start at line 1.
    _, sep, body = text.partition("\n---\n")
    if not sep:
        raise SystemExit(f"{SOURCE} has no YAML frontmatter")
    head = text[: len(text) - len(body)]
    return f"{head}\n{NOTE}{body.lstrip(chr(10))}"


def main() -> int:
    check = "--check" in sys.argv
    want = rendered()
    failed = False
    for target in TARGETS:
        current = target.read_text(encoding="utf-8") if target.exists() else None
        if current == want:
            continue
        if check:
            print(f"out of date: {target.relative_to(ROOT)} (run `make sync-skills`)")
            failed = True
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(want, encoding="utf-8", newline="\n")
            print(f"wrote {target.relative_to(ROOT)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
