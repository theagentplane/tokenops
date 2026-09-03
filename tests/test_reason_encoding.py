"""Governance reasons must survive a legacy console encoding.

A ``reason`` is user-facing: it is printed, logged, and shown in the Dashboard.
On Windows, stdout defaults to cp1252 whenever it is redirected, which covers
piping to a file and most CI runners. A single non-ASCII character in a reason
turns a correct governance decision into a ``UnicodeEncodeError`` that kills the
process, so the enforcement works and the report of it crashes.

This guards the source rather than waiting for a policy to trip, because a
reason is only built on the path that trips it and most paths are rare.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parent.parent / "src" / "tokenops"
Failed = pytest.fail.Exception
LEGACY_ENCODING = "cp1252"


def _reason_strings(path: pathlib.Path) -> list[tuple[int, str]]:
    """Every literal text passed as ``reason=``, including inside f-strings."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg != "reason":
                continue
            if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                found.append((kw.value.lineno, kw.value.value))
            elif isinstance(kw.value, ast.JoinedStr):
                # An f-string: only the literal segments can carry a stray glyph.
                for part in kw.value.values:
                    if isinstance(part, ast.Constant) and isinstance(part.value, str):
                        found.append((kw.value.lineno, part.value))
    return found


POLICY_FILES = sorted((SRC / "control" / "policies").glob("*.py"))


@pytest.mark.parametrize("path", POLICY_FILES, ids=lambda p: p.name)
def test_policy_reasons_encode_on_a_legacy_console(path: pathlib.Path) -> None:
    """Use >= not U+2265, ~ not U+2248, x not U+00D7, and a comma not an em dash."""
    for lineno, text in _reason_strings(path):
        try:
            text.encode(LEGACY_ENCODING)
        except UnicodeEncodeError as exc:
            bad = text[exc.start : exc.end]
            pytest.fail(
                f"{path.name}:{lineno} reason contains {bad!r} "
                f"(U+{ord(bad[0]):04X}), which raises UnicodeEncodeError on a "
                f"{LEGACY_ENCODING} console. Use an ASCII equivalent."
            )


def test_the_guard_actually_looks_at_something() -> None:
    """A silent zero-match scan would pass forever. Assert it found real reasons."""
    total = sum(len(_reason_strings(p)) for p in POLICY_FILES)
    assert len(POLICY_FILES) >= 10, "policy modules disappeared; fix this test's glob"
    assert total >= 10, f"expected many reason= strings across policies, found {total}"


def test_the_guard_catches_a_reintroduction(tmp_path: pathlib.Path) -> None:
    """The check must fail on the exact pattern that was removed."""
    offender = tmp_path / "bad_policy.py"
    offender.write_text(
        'Signal(reason=f"step cap reached: {n} ≥ {cap}")\n',
        encoding="utf-8",
    )
    with pytest.raises(Failed):
        test_policy_reasons_encode_on_a_legacy_console(offender)
