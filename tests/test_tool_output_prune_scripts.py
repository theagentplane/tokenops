"""tool_output_prune for JavaScript/TypeScript, shell and SQL: the lexers, the handlers and the safety contract."""

from __future__ import annotations

import pytest

from tokenops.framework import ApplyControls, build_governor
from tokenops.framework.pruning import NOTE, prune, prune_any, select_handler
from tokenops.framework.pruning_jslex import lex_js
from tokenops.framework.pruning_languages import HANDLERS, resolve_languages
from tokenops.framework.pruning_shlex import lex_shell
from tokenops.framework.pruning_sqllex import lex_sql

JS = r"""#!/usr/bin/env node
// @ts-check
/**
 * Loads a thing from the server and returns the parsed body of the response, which is a long sentence.
 * @param {string} url the url to fetch
 */
import fs from "fs";

/** Plain description with no type tag, long enough to be worth hiding when the policy is on. */
const re = /\/\/[a-z]+\*/g; // a regex with comment markers inside
const half = total / 2; // a division, then a comment
/* block */ const t = `see http://x.com/${name.toUpperCase()}/y`; // template with a URL
const s = 'it\'s // not a comment'; /* trailing block */
async function load(url) {
  const r = await fetch(url, { headers: {} }); // fetch it
  if (/^\/\*/.test(url)) return null;
  return r.json();
}
module.exports = { load, re, half, t, s };
"""

TS = r"""/// <reference types="node" />
import { readFile } from "fs/promises";

// The shape of a user record as stored by the service, with a long enough explanation to hide.
export interface User {
  id: number; // primary key
  name: string;
}

/** Reads a user from disk and returns it, or undefined when the file does not exist at all. */
export async function loadUser(path: string): Promise<User | undefined> {
  // @ts-expect-error the typings are wrong here
  const raw = await readFile(path, "utf8"); // read
  const half: number = (raw.length + 1) / 2; // average
  return JSON.parse(raw) as User; /* cast */
}
"""

SH = r"""#!/bin/bash
# Deploy script, with a long explanation of what it does and why it exists in the repository.
set -euo pipefail
# shellcheck disable=SC2086
name="$1" # the name
count=${#name}
rest=${name#prefix}
echo "$count # not a comment" 'a#b' $((16#ff)) $# "$(echo "x" # real comment
)"
for f in *.txt; do
  echo $f # trailing
done
if [ -z "$name" ]; then
  exit 1 # bail
fi
"""

SH_HEREDOC = r"""#!/bin/sh
# write the config
cat > /etc/app.conf <<EOF
# this is the file's own comment, not the script's
key = value
EOF
cat <<-'TAG'
	# also content
	TAG
set -e # done
echo "all # fine"
echo end
"""

SQL = r"""-- Create the users table, with a long explanation of what it is for and how it is used here.
CREATE TABLE users (
  id BIGINT PRIMARY KEY, -- the id
  name TEXT NOT NULL DEFAULT 'a -- not a comment'
);
/* block comment /* nested */ that goes on for a while to be worth hiding */
CREATE FUNCTION f() RETURNS text AS $$
  SELECT 'x -- body text'; -- inside the dollar quote
$$ LANGUAGE sql;
SELECT /*+ INDEX(u) */ * FROM users u WHERE name = 'it''s' -- tail
ORDER BY id;
/*!40101 SET NAMES utf8 */;
-- +goose Up
"""

SOURCES = {"js": JS, "ts": TS, "shell": SH, "sql": SQL}
HANDLER_OF = {"js": "js", "ts": "js", "shell": "shell", "sql": "sql"}
LEXERS = {"js": lex_js, "shell": lex_shell, "sql": lex_sql}


def out_of(key: str, text: str, **kw) -> str:
    out = prune(text, HANDLERS[HANDLER_OF[key]], min_saved_chars=-10_000, **kw)
    assert out is not None, key
    return out


def check_contract(key: str, text: str, out: str) -> None:
    body = out[: out.rindex(NOTE)]
    assert len(body.split("\n")) == len(text.split("\n"))
    lex = LEXERS[HANDLER_OF[key]]
    a, b = lex(text), lex(body)
    assert a is not None and b is not None and a.skeleton == b.skeleton


@pytest.mark.parametrize("key", list(SOURCES))
def test_prunes_and_keeps_the_contract(key):
    text = SOURCES[key]
    out = out_of(key, text)
    check_contract(key, text, out)
    assert out != text and NOTE in out


def test_js_hides_comments_keeps_strings_regexes_templates_and_directives():
    out = out_of("js", JS)
    assert out.startswith("#!/usr/bin/env node\n// @ts-check\n")
    assert "a regex with comment markers" not in out and "a division, then" not in out
    assert "Plain description" not in out and "trailing block" not in out and "fetch it" not in out
    assert r"const re = /\/\/[a-z]+\*/g;" in out
    assert "const half = total / 2;" in out
    assert "const t = `see http://x.com/${name.toUpperCase()}/y`;" in out
    assert r"const s = 'it\'s // not a comment';" in out
    assert r"if (/^\/\*/.test(url)) return null;" in out
    # a JSDoc block with type tags stays by default, and goes with keep_jsdoc_types=False
    assert "@param {string} url" in out
    hidden = prune(
        JS, resolve_languages(["js"], keep_jsdoc_types=False)[0], min_saved_chars=-10_000
    )
    assert hidden is not None and "@param {string} url" not in hidden
    assert "/* (doc hidden) */" in hidden and "// @ts-check" in hidden


def test_ts_directives_stay_and_comments_go():
    out = out_of("ts", TS)
    assert '/// <reference types="node" />' in out and "// @ts-expect-error" in out
    assert "primary key" not in out and "The shape of a user" not in out and "average" not in out
    assert "Reads a user from disk" not in out and "/* cast */" not in out
    assert "const half: number = (raw.length + 1) / 2;" in out


@pytest.mark.parametrize(
    ("code", "comment_count"),
    [
        ("a = b / c / d; // x\n", 1),
        ("a = (b + c) / 2 // x\n", 1),
        ("i++ / 2 // x\n", 1),
        ("x = y.return / 2 // x\n", 1),
        ("return /a\\/\\/b/.test(s) // x\n", 1),
        ("s = a ? /[/]\\//g : 0 // x\n", 1),
        ("x = `${`${a}//`}` // x\n", 1),
    ],
)
def test_js_regex_division_and_template_cases(code, comment_count):
    lexed = lex_js(code)
    assert lexed is not None and len(lexed.comments) == comment_count
    assert code[lexed.comments[0].start :].strip() == "// x"


@pytest.mark.parametrize(
    "text",
    [
        "}\n/ x /\n",  # `/` after `}`: a division or a regex, cannot tell
        "x = `${a / b}`;\n",  # a `/` inside a template expression
        "x = `${a /* c */}`;\n",
        "const a = <div>// not a comment</div>;\n",  # JSX
        "const a = <Foo />;\n",
        "x = 1;\n /* the text ends inside a block comment\n y = 2;\n",
        " * the text starts inside a block comment\n */\nx = 1;\n",
        "const s = 'never closed;\n",
        "const r = /never closed;\n",
    ],
)
def test_js_lexer_refuses_what_it_cannot_be_sure_of(text):
    assert lex_js(text) is None


def test_shell_hash_rules():
    lexed = lex_shell("echo ${#x} $# a#b $((16#ff)) \"#q\" '#s' $'#\\'t' \\# # real\n")
    assert lexed is not None and len(lexed.comments) == 1
    text = SH
    out = out_of("shell", text)
    assert "#!/bin/bash" in out and "# shellcheck disable=SC2086" in out
    assert "Deploy script" not in out and "the name" not in out and "trailing" not in out
    assert "bail" not in out
    # a comment inside "$( ... )" in double quotes is skipped with the string: it stays, which is safe
    assert "real comment" in out
    assert "echo \"$count # not a comment\" 'a#b' $((16#ff)) $#" in out
    assert "rest=${name#prefix}" in out


def test_shell_heredoc_bodies_are_content_not_comments():
    out = out_of("shell", SH_HEREDOC)
    assert "# this is the file's own comment, not the script's" in out
    assert "\t# also content" in out
    assert "write the config" not in out and "# done" not in out
    check_contract("shell", SH_HEREDOC, out)


@pytest.mark.parametrize(
    "text",
    [
        "cat <<EOF\nbody\n",  # ends inside the heredoc
        "cat <<EOF\n",  # ends before the body
        "echo 'never closed\n",
        'echo "never closed\n',
        'echo "$(never closed"\n',
        "echo `never closed\n",
    ],
)
def test_shell_lexer_refuses_what_it_cannot_be_sure_of(text):
    assert lex_shell(text) is None


def test_shell_refuses_a_markdown_fence_and_is_not_in_auto():
    fenced = "```bash\n" + SH + "```\n"
    assert prune(fenced, HANDLERS["shell"], min_saved_chars=-10_000) is None
    assert "shell" not in [h.name for h in resolve_languages("auto")]
    assert [h.name for h in resolve_languages(["bash"])] == ["shell"]


def test_sql_comments_strings_hints_and_dialect_refusals():
    out = out_of("sql", SQL)
    assert "the id" not in out and "Create the users table" not in out and "nested" not in out
    assert (
        "inside the dollar quote" in out and "x -- body text" in out
    )  # dollar-quoted body is content
    assert "'a -- not a comment'" in out and "'it''s'" in out
    assert (
        "/*+ INDEX(u) */" in out and "/*!40101 SET NAMES utf8 */;" in out and "-- +goose Up" in out
    )
    assert "tail" not in out
    for text in (
        "SELECT 'it\\'s -- x' FROM t;\n",  # backslash before the closing quote: dialect-dependent
        "SELECT 1; # mysql comment\n",
        "SELECT 'never closed;\n",
        "SELECT $$ never closed\n",
        "SELECT 1; /* ends inside\n",
        " the text starts inside */ SELECT 1;\n",
    ):
        assert lex_sql(text) is None, text
    assert lex_sql("SELECT $1, #temp FROM t -- c\n") is not None  # $1 and #temp are not special


@pytest.mark.parametrize("key", ["js", "ts", "shell", "sql"])
def test_fragments_are_pruned_safely_or_left_alone(key):
    """A sed -n range can start or end anywhere: every window is refused or satisfies the contract."""
    lines = SOURCES[key].rstrip("\n").split("\n")
    if key == "shell":  # drop the multi-line command substitution; a window can cut it in half
        lines = [ln for ln in lines if "real comment" not in ln and ln != ')"']
    pruned = 0
    for start in range(len(lines)):
        for size in (9, 14, 22):
            frag = "\n".join(lines[start : start + size]) + "\n"
            if frag.count("\n") < 9:
                continue
            out = prune(frag, HANDLERS[HANDLER_OF[key]], min_saved_chars=-10_000)
            if out is None:
                continue
            pruned += 1
            check_contract(key, frag, out)
    assert pruned > 0


@pytest.mark.parametrize("key", list(SOURCES))
def test_diffs_grep_hits_and_numbered_listings_are_untouched(key):
    handler = HANDLERS[HANDLER_OF[key]]
    lines = SOURCES[key].rstrip("\n").split("\n")
    diff = "diff --git a/x b/x\n@@ -1,3 +1,3 @@\n" + "\n".join("+" + ln for ln in lines) + "\n"
    grep = "\n".join(f"src/x.js:{i}:{ln}" for i, ln in enumerate(lines, 1)) + "\n"
    nl = "\n".join(f"{i:6d}\t{ln}" for i, ln in enumerate(lines, 1)) + "\n"
    for text in (diff, grep, nl):
        assert prune_any(text, [handler], min_saved_chars=-10_000) is None


def test_data_and_markup_are_never_pruned_even_with_every_handler():
    everything = list(HANDLERS.values())  # shell included
    json_text = (
        "{\n" + ",\n".join(f'  "k{i}": "-- v {i} /* x */ // y # z"' for i in range(20)) + "\n}\n"
    )
    yaml_text = "\n".join(f"key{i}: value # comment {i}" for i in range(20)) + "\n"
    md = (
        "\n".join(f"# Heading {i}\n// not code {i} /* nor this */ -- nor this" for i in range(10))
        + "\n"
    )
    for text in (json_text, yaml_text, md):
        assert prune_any(text, everything, min_saved_chars=-10_000) is None


@pytest.mark.parametrize("key", list(SOURCES))
def test_each_language_is_detected_from_the_text(key):
    everything = list(HANDLERS.values())
    picked = select_handler(SOURCES[key], everything)
    assert picked is not None and picked.name == HANDLER_OF[key]


def test_the_previous_languages_are_still_detected_with_the_new_handlers_present():
    from tests.test_tool_output_prune_languages import SOURCES as OLD  # noqa: PLC0415

    for name, text in OLD.items():
        picked = select_handler(text, list(HANDLERS.values()))
        assert picked is not None and picked.name == name, name


def test_policy_and_config_accept_the_new_languages():
    controls = ApplyControls()
    policies = {
        "tool_output_prune": {
            "languages": ["ts", "sql"],
            "keep_jsdoc_types": False,
            "min_saved_chars": 0,
        }
    }
    governor = build_governor({"budgets": [], "policies": policies}, lambda *a, **k: 0, controls)
    shaped = governor.shape_tool_result("b", JS)
    assert shaped is not None and "@param {string} url" not in shaped
    assert governor.shape_tool_result("b", SH) is None, "shell is not enabled"
    sql = governor.shape_tool_result("b", SQL)
    assert sql is not None and "the id" not in sql
