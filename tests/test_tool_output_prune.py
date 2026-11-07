"""tool_output_prune — hide comments and docstrings in a tool result that is Python source, from the text alone."""

from __future__ import annotations

import ast

import pytest

from tokenops.capabilities.crossing import _shape_tool_result
from tokenops.framework import ApplyControls, build_governor
from tokenops.framework.pruning import (
    HIDDEN_DOCSTRING,
    NOTE,
    looks_like_python_source,
    prune_python,
)

LONG = "\n".join(
    f"    Line {i} of a long explanation that says what the function does and why it exists."
    for i in range(10)
)
SRC = f'''"""Module docstring that explains the module at some length, so hiding it is worth a note.
It runs over several lines to look like the real thing in a real code base."""
import os  # trailing comment


# whole-line comment
def f(x, y):
    """Return x.

{LONG}
    """
    s = "a # inside a string"  # type: str
    if x:
        return x  # noqa
    return y


class C:
    """Doc of the class, also long enough to matter when it is shown to a model at every call."""

    def g(self):  # why this
        y = """a string that is not a docstring"""
        return y
'''


def test_comments_and_docstrings_go_and_code_stays():
    out = prune_python(SRC)
    assert out is not None and out.endswith(NOTE + "\n")
    body = out[: -len(NOTE) - 1]
    assert body.count("\n") == SRC.count("\n") - 0 or body.count("\n") + 1 == SRC.count("\n") + 1
    assert (
        "trailing comment" not in out and "whole-line comment" not in out and "why this" not in out
    )
    assert (
        "Line 3 of a long" not in out
        and "Module docstring" not in out
        and "Doc of the class" not in out
    )
    assert out.count(HIDDEN_DOCSTRING) == 3
    for kept in (
        's = "a # inside a string"  # type: str',
        "return x  # noqa",
        'y = """a string that is not a docstring"""',
        "import os",
        "def f(x, y):",
        "if x:",
        "    return y",
    ):
        assert kept in out
    ast.parse(body)


def test_line_count_is_unchanged():
    out = prune_python(SRC)
    assert out is not None
    assert out[: -len(NOTE) - 1].rstrip("\n").count("\n") == SRC.rstrip("\n").count("\n")


def test_fragment_inside_a_function_still_prunes_its_docstring():
    lines = SRC.split("\n")
    start = next(i for i, ln in enumerate(lines) if ln.startswith("def f"))
    out = prune_python("\n".join(lines[start : start + 18]) + "\n")
    assert out is not None and "Line 3 of a long" not in out and "def f(x, y):" in out


def test_fragment_starting_inside_a_docstring_is_left_alone_or_safe():
    lines = SRC.split("\n")
    mid = next(i for i, ln in enumerate(lines) if "Line 4 of" in ln)
    frag = "\n".join(lines[mid:]) + "\n"
    out = prune_python(frag)
    # either refused, or every code line of the fragment survives untouched
    if out is not None:
        for kept in ("return x  # noqa", "def g(self):", "return y"):
            assert kept in out


@pytest.mark.parametrize(
    "text",
    [
        "",
        "hello world\n",
        "\n".join(f"line {i}" for i in range(50)),  # prose
        "diff --git a/x.py b/x.py\n@@ -1,3 +1,3 @@\n"
        + "\n".join(f"+    # c{i}\n     return {i}" for i in range(30)),
        "\n".join(f"pkg/mod.py:{i}:    # comment {i}" for i in range(30)),  # grep -n
        "\n".join(f"{i:6}\t    def f{i}(): pass  # c" for i in range(30)),  # cat -n
        "=== FAILURES ===\n" + "\n".join(f"E   assert {i}" for i in range(30)),
    ],
)
def test_output_that_is_not_python_source_is_untouched(text):
    assert prune_python(text) is None


def test_looks_like_python_requires_structure():
    assert looks_like_python_source(SRC)
    assert not looks_like_python_source("x = 1\n" * 20)  # lines, but no def/class/import structure


def test_small_savings_are_not_worth_the_note():
    src = "import os\n" + "\n".join(f"def f{i}():\n    return {i}  # c" for i in range(6)) + "\n"
    assert prune_python(src, min_saved_chars=200) is None
    assert prune_python(src, min_saved_chars=-1000) is not None


def test_directives_and_shebang_survive():
    src = "#!/usr/bin/env python\n# -*- coding: utf-8 -*-\n" + SRC.replace(
        '"""Module', '"""Module', 1
    )
    out = prune_python(src)
    assert out is not None and "#!/usr/bin/env python" in out and "coding: utf-8" in out


def test_only_comments_or_only_docstrings():
    only_comments = prune_python(SRC, docstrings=False, min_saved_chars=-1000)
    assert (
        only_comments is not None
        and "whole-line comment" not in only_comments
        and "Line 3 of a long" in only_comments
    )
    only_docs = prune_python(SRC, comments=False, min_saved_chars=-1000)
    assert (
        only_docs is not None
        and "whole-line comment" in only_docs
        and "Line 3 of a long" not in only_docs
    )


def _governor(**policies):
    controls = ApplyControls()
    governor = build_governor({"budgets": [], "policies": policies}, lambda *a, **k: 0, controls)
    return governor, controls


def test_template_shapes_a_dict_result_and_leaves_the_text_on_the_controls():
    governor, controls = _governor(tool_output_prune={})
    result = {"output": SRC, "returncode": 0}
    seen = _shape_tool_result(governor, controls, "bash", result)
    assert seen["returncode"] == 0 and HIDDEN_DOCSTRING in seen["output"]
    assert result["output"] == SRC, "the wrapped function's own result is never changed"
    assert controls.take_shaped_result() == seen["output"]
    assert controls.take_shaped_result() is None, "one-shot"


def test_not_configured_means_nothing_happens():
    governor, controls = _governor(tool_output_cap={"cap_tokens": 1400})
    assert _shape_tool_result(governor, controls, "bash", {"output": SRC}) == {"output": SRC}
    assert controls.take_shaped_result() is None


def test_non_text_results_pass_through():
    governor, controls = _governor(tool_output_prune={})
    for r in (None, 3, {"rows": [1, 2]}, ["a"]):
        assert _shape_tool_result(governor, controls, "x", r) == r
