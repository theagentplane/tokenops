"""tool_output_prune for Go, Java, Rust and C/C++: the shared lexer, the handlers, detection and the safety contract."""

from __future__ import annotations

import pytest

from tokenops.framework import ApplyControls, build_governor
from tokenops.framework.pruning import NOTE, prune, prune_any, select_handler
from tokenops.framework.pruning_clex import lex_c_style
from tokenops.framework.pruning_languages import HANDLERS, resolve_languages
from tokenops.framework.pruning_types import CLexConfig

GO = """//go:build linux

// Package store keeps the things we store, and it keeps them in memory for as long as the process lives.
package store

/*
#include <stdlib.h>
*/
import "C"

import (
	"fmt"
	"strings"
)

// Store is a keyed store. It is safe for concurrent use by multiple goroutines,
// and the zero value is ready to use. This sentence only exists to be long enough.
type Store struct {
	m map[string]string // guarded by mu
}

// Get returns the value for key and whether it was present in the store at the time of the call.
func (s *Store) Get(key string) (string, bool) {
	v, ok := s.m[key] // lookup
	url := "http://example.com/*not a comment*/"
	raw := `// still not a comment`
	/* a block
		comment inside a function */
	return strings.TrimSpace(v) + url + raw, ok
}

//go:generate stringer -type=Kind
func Dump(s *Store) {
	//nolint:errcheck
	fmt.Println(s.m)
}
"""

JAVA = '''/*
 * Copyright 2020 Example Corp. Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package com.example.store;

import java.util.HashMap;
import java.util.Map;

/**
 * A keyed store. It is not thread safe, and it keeps every entry in memory for the life of the instance.
 *
 * @author someone
 */
public class Store {
    private final Map<String, String> map = new HashMap<>(); // the backing map

    /**
     * Returns the value for the key, or null when the key is absent from the map at the time of the call.
     * @param key the key to look up
     * @return the value
     */
    @Override
    public String get(String key) throws IllegalStateException {
        // fast path
        String url = "http://example.com/* not a comment */";
        String block = """
            // text block, not a comment
            /* nor this */
            """;
        char slash = '/'; /* trailing block */
        return map.get(key) + url + block + slash;
    }
}
'''

RUST = """//! Crate level documentation that explains what the crate is for and how it is laid out in some detail.

use std::collections::HashMap;

/// A keyed store. It keeps every entry in memory for as long as the value lives,
/// and it never grows beyond the capacity it was created with.
pub struct Store<'a> {
    map: HashMap<&'a str, String>, // the backing map
}

impl<'a> Store<'a> {
    /// Returns the value for the key, if any, without copying it out of the map at all.
    pub fn get(&self, key: &'a str) -> Option<&String> {
        // SAFETY: nothing unsafe happens here, this only checks that SAFETY comments are kept.
        let raw = r#"// not a comment, "quoted" and all"#;
        let c = 'x'; /* outer /* nested */ still a comment */
        let q = '\\'';
        let _ = (raw, c, q);
        self.map.get(key)
    }
}
"""

C_SRC = """/*! SPDX license block that must stay */
#include <stdio.h>
#include <stdlib.h>
#pragma once

/* A keyed store. It keeps every entry in memory for as long as the process lives,
 * and it never grows beyond the capacity it was created with at start up.
 */
struct store {
    int n;   /* number of entries */
    char *k; // the keys
};

// Returns the value for the key, or NULL when the key is absent from the store at the time of the call. \\
   this line is still part of the same comment
static char *store_get(struct store *s, const char *key)
{
    const char *url = "http://example.com/* not a comment */";
    int big = 1'000'000; // digit separator in C++14
    /* NOLINT */ int x = 0;
    switch (x) {
    case 0: /* fallthrough */
    default:
        break;
    }
    if (s == NULL) {  // check
        return NULL;
    }
    printf("%s\\n", url); /* done */ x++; /* again */
    return s->k;
}
"""

SOURCES = {
    "go": GO,
    "java": JAVA,
    "rust": RUST,
    "c": C_SRC,
}


def out_of(name: str, text: str, **kw) -> str:
    out = prune(text, HANDLERS[name], min_saved_chars=-10_000, **kw)
    assert out is not None, name
    return out


def body_of(out: str) -> str:
    assert out.rstrip("\n").endswith(NOTE)
    return out[: out.rindex(NOTE)]


def check_contract(name: str, text: str, out: str) -> None:
    body = body_of(out)
    # line count unchanged (the note is the only extra line)
    assert len(body.split("\n")) == len(text.split("\n"))
    cfg = HANDLERS[name].cfg  # type: ignore[attr-defined]
    a, b = lex_c_style(text, cfg), lex_c_style(body, cfg)
    assert a is not None and b is not None and a.skeleton == b.skeleton


@pytest.mark.parametrize("name", list(SOURCES))
def test_prunes_and_keeps_the_contract(name):
    text = SOURCES[name]
    out = out_of(name, text)
    check_contract(name, text, out)
    assert len(out) < len(text)
    assert NOTE in out


def test_go_prunes_comments_and_keeps_directives_and_cgo():
    out = out_of("go", GO)
    assert "//go:build linux" in out and "//go:generate stringer -type=Kind" in out
    assert "//nolint:errcheck" in out
    assert "#include <stdlib.h>" in out  # the cgo preamble above import "C" is code
    assert "guarded by mu" not in out and "lookup" not in out and "a block" not in out
    assert "A keyed store" not in out and "Package store keeps" not in out
    assert "/* (doc hidden) */" in out
    assert 'url := "http://example.com/*not a comment*/"' in out
    assert "raw := `// still not a comment`" in out
    assert "\treturn strings.TrimSpace(v) + url + raw, ok" in out.split("\n")


def test_java_hides_javadoc_and_comments_keeps_strings():
    out = out_of("java", JAVA)
    assert "A keyed store" not in out and "fast path" not in out and "trailing block" not in out
    assert "Copyright 2020" not in out  # a plain license block is an ordinary comment
    assert "// text block, not a comment" in out and "/* nor this */" in out
    assert 'String url = "http://example.com/* not a comment */";' in out
    assert "char slash = '/';" in out
    assert "    @Override" in out and "throws IllegalStateException" in out


def test_rust_nested_comments_raw_strings_lifetimes_and_safety():
    out = out_of("rust", RUST)
    assert "// SAFETY: nothing unsafe" in out
    assert "outer" not in out and "nested" not in out
    assert 'let raw = r#"// not a comment, "quoted" and all"#;' in out
    assert "pub struct Store<'a> {" in out and "key: &'a str" in out
    assert "A keyed store" not in out and "Crate level documentation" not in out


def test_c_keeps_license_pragma_markers_and_handles_cpp_bits():
    out = out_of("c", C_SRC)
    assert "/*! SPDX license block that must stay */" in out and "#pragma once" in out
    assert "/* NOLINT */ int x = 0;" in out and "case 0: /* fallthrough */" in out
    assert "int big = 1'000'000;" in out
    assert "A keyed store" not in out and "number of entries" not in out
    assert "this line is still part" not in out  # a // comment continued by a backslash
    assert 'printf("%s\\n", url); x++;' in out
    assert 'const char *url = "http://example.com/* not a comment */";' in out


def test_only_comments_or_only_docs():
    only_comments = out_of("java", JAVA, docstrings=False)
    assert "A keyed store" in only_comments and "fast path" not in only_comments
    only_docs = out_of("java", JAVA, comments=False)
    assert "A keyed store" not in only_docs and "fast path" in only_docs


def test_cpp_raw_string_and_text_with_markers_in_strings():
    src = (
        'const char *a = R"x(// not /* a comment */ )x";\n'
        'const char *b = "\\" // escaped quote then marker";\n'
        "int c = 1; // real\n"
    )
    lexed = lex_c_style(src, HANDLERS["c"].cfg)  # type: ignore[attr-defined]
    assert lexed is not None and len(lexed.comments) == 1
    assert src[lexed.comments[0].start : lexed.comments[0].end] == "// real"


def test_rust_lifetime_is_not_a_char_and_nested_comment_closes():
    cfg = HANDLERS["rust"].cfg  # type: ignore[attr-defined]
    lexed = lex_c_style("fn f<'a>(x: &'a str) -> &'a str { x } /* a /* b */ c */ // d\n", cfg)
    assert lexed is not None and [c.block for c in lexed.comments] == [True, False]
    plain = lex_c_style(
        "/* a /* b */ c */", CLexConfig()
    )  # C does not nest: the text after */ is code
    assert plain is None  # a stray */ after the first close


@pytest.mark.parametrize(
    "text",
    [
        "int x = 1;\n /* the text ends inside a block comment\n int y = 2;\n",
        " * the text starts inside a block comment\n */\nint x = 1;\n",
        'const char *s = "never closed;\n',
    ],
)
def test_lexer_refuses_what_it_cannot_be_sure_of(text):
    assert lex_c_style(text, CLexConfig()) is None


@pytest.mark.parametrize("name", list(SOURCES))
def test_fragments_are_pruned_safely_or_left_alone(name):
    """A sed -n range can start or end anywhere: every window must be refused or satisfy the contract."""
    text = SOURCES[name].rstrip("\n")
    lines = text.split("\n")
    pruned = 0
    for start in range(len(lines)):
        for size in (9, 14, 22):
            frag = "\n".join(lines[start : start + size]) + "\n"
            if frag.count("\n") < 9:
                continue
            out = prune(frag, HANDLERS[name], min_saved_chars=-10_000)
            if out is None:
                continue
            pruned += 1
            check_contract(name, frag, out)
    assert pruned > 0


@pytest.mark.parametrize("name", list(SOURCES))
def test_diffs_grep_hits_and_numbered_listings_are_untouched(name):
    lines = SOURCES[name].rstrip("\n").split("\n")
    diff = "diff --git a/x b/x\n@@ -1,3 +1,3 @@\n" + "\n".join("+" + ln for ln in lines) + "\n"
    grep = "\n".join(f"src/x.go:{i}:{ln}" for i, ln in enumerate(lines, 1)) + "\n"
    nl = "\n".join(f"{i:6d}\t{ln}" for i, ln in enumerate(lines, 1)) + "\n"
    for text in (diff, grep, nl):
        assert prune_any(text, list(HANDLERS.values()), min_saved_chars=-10_000) is None


def test_data_and_markup_are_never_pruned():
    everything = list(HANDLERS.values())
    json_text = "{\n" + ",\n".join(f'  "k{i}": "// v {i} /* x */"' for i in range(20)) + "\n}\n"
    yaml_text = "\n".join(f"key{i}: value # comment {i}" for i in range(20)) + "\n"
    md = "\n".join(f"# Heading {i}\n// not code {i} /* nor this */" for i in range(10)) + "\n"
    for text in (json_text, yaml_text, md):
        assert prune_any(text, everything, min_saved_chars=-10_000) is None


@pytest.mark.parametrize("name", list(SOURCES))
def test_auto_detects_the_language_from_the_text(name):
    everything = list(HANDLERS.values())
    picked = select_handler(SOURCES[name], everything)
    assert picked is not None and picked.name == name
    assert prune_any(SOURCES[name], everything, min_saved_chars=-10_000) is not None


def test_ambiguous_text_is_refused():
    # A line of Go and a line of Java each, in equal measure: neither wins clearly.
    mixed = (
        'package main\nimport "fmt"\nfunc a() {}\nfunc b() {}\n'
        "package com.x;\nimport java.util.List;\n@Override\n@Test\n// c\n// d\n"
    )
    assert select_handler(mixed, list(HANDLERS.values())) is None
    assert prune_any(mixed, list(HANDLERS.values()), min_saved_chars=-10_000) is None


def test_python_is_not_mistaken_for_a_c_style_language():
    from tests.test_tool_output_prune import (
        SRC,  # noqa: PLC0415 - a Python text from the Python tests
    )

    assert select_handler(SRC, list(HANDLERS.values())).name == "python"  # type: ignore[union-attr]


def test_default_languages_is_python_only():
    gov_detector = __import__(
        "tokenops.framework.policies.tool_output_prune", fromlist=["x"]
    ).ToolOutputPruneDetector()
    assert [h.name for h in gov_detector.handlers] == ["python"]
    assert gov_detector.shape_tool_result("b", GO) is None


def test_policy_prunes_go_when_enabled():
    from tokenops.framework.policies.tool_output_prune import (
        ToolOutputPruneDetector,  # noqa: PLC0415
    )

    det = ToolOutputPruneDetector(languages=["go"], min_saved_chars=0)
    out = det.shape_tool_result("b", GO)
    assert out is not None and "A keyed store" not in out


def test_resolve_languages():
    assert [h.name for h in resolve_languages("auto")] == [k for k in HANDLERS if k != "shell"]
    assert [h.name for h in resolve_languages(["C++", "golang", "c"])] == ["c", "go"]
    with pytest.raises(ValueError, match="unknown language"):
        resolve_languages(["cobol"])
    with pytest.raises(ValueError, match="at least one"):
        resolve_languages([])


def test_languages_param_flows_through_the_config():
    controls = ApplyControls()
    policies = {"tool_output_prune": {"languages": ["go", "rust"], "min_saved_chars": 0}}
    governor = build_governor({"budgets": [], "policies": policies}, lambda *a, **k: 0, controls)
    shaped = governor.shape_tool_result("b", GO)
    assert shaped is not None and "A keyed store" not in shaped
    assert governor.shape_tool_result("b", JAVA) is None, "java is not enabled"
    with pytest.raises(ValueError, match="unknown language"):
        build_governor(
            {"budgets": [], "policies": {"tool_output_prune": {"languages": ["cobol"]}}},
            lambda *a, **k: 0,
            ApplyControls(),
        )
