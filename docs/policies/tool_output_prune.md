# Tool output prune

*Hide what a coding agent rarely needs from a tool result, before the cap measures it.*

**Policy ID:** [`tool_output_prune`](../product/policies-index.md)

Companion to [`tool_output_cap.md`](tool_output_cap.md). Opt-in.

Code: [`src/tokenops/framework/policies/tool_output_prune.py`](../../src/tokenops/framework/policies/tool_output_prune.py),
[`src/tokenops/framework/pruning.py`](../../src/tokenops/framework/pruning.py)
Tests: [`tests/test_tool_output_prune.py`](../../tests/test_tool_output_prune.py),
[`tests/test_tool_output_prune_languages.py`](../../tests/test_tool_output_prune_languages.py)

---

## TL;DR

A coding agent reads source files through its shell, and comments and docstrings are a large share of those tokens
(about 20 to 30% of a Python view). The action is to **rewrite** the result: the same text with comments and
docstrings hidden. Code lines stay verbatim and the number of lines is unchanged (a hidden block becomes blank lines), so
exact-text edits and cited line numbers still hold. Never HALT, never drops code.

It works from the result text alone, not from the command, so it only acts when it can show the text is source code in an
enabled language. Python is the default; Go, Java, Rust and C/C++ are available with `languages`.

## Detect

```
text is a block of source in language L  :=  >= 8 non-blank lines
                                      and it lexes cleanly (no error tokens, no open string, no open or stray
                                          block comment at either end)
                                      and enough lines have L's structure (Python: def, class, import, return,
                                          if ...:; Go: package, func, :=; Java: package, import, access modifiers;
                                          Rust: fn, let, impl, use; C/C++: #include, typedef, NULL, std::)
                                      and it is not a diff, a grep -n hit list, a cat -n listing or a test report
```

With several languages enabled the text is scored against each one, and it is **refused when the top two scores are close**
(the best must be at least 1.5 times the runner-up and 2 more). JSON, YAML and Markdown have no such structure and are
never pruned.

## What it hides

- Comments (a whole-line comment becomes a blank line; a trailing one is trimmed). Tool directives stay:
  `# type:`, `# noqa`, `# pragma`, `# fmt:`, `# pylint:`, shebang and encoding lines.
- Docstrings it can prove are docstrings: the first statement of the text at column 0, or the first statement of a
  block whose `def`/`class` header is in the text. Replaced by `"""(docstring hidden)"""` and blank lines.

When the whole text parses as Python, the result must have the same syntax tree as the original apart from docstrings, or
nothing is changed. A note is appended to say that something was hidden.

### Other languages

| Language | Comments | Doc comments (replaced by `/* (doc hidden) */` and blank lines) | Stays |
|---|---|---|---|
| Go | `//`, `/* */` | the `//` block directly above `func`, `type`, `var`, `const` or `package` | `//go:...`, `//nolint`, `//export`, `// +build`, and the comment right above `import "C"` (cgo code) |
| Java | `//`, `/* */` | `/** */`, `///` | `//noinspection`, `// NOSONAR`, `/*! */` |
| Rust | `//`, `/* */` (nests) | `///`, `//!`, `/** */`, `/*! */` | `// SAFETY:`, `// rustfmt`, `// clippy` |
| C / C++ | `//` (a trailing `\` continues it), `/* */` | `/** */`, `///`, `//!` | `// NOLINT`, `/* fallthrough */`, `/*! license */`; `#pragma` and `#if 0` are code |
| JavaScript / TypeScript (`js`, aliases `ts`, `javascript`, `typescript`) | `//`, `/* */` | `/** */` JSDoc, **unless it has a type tag** (`@param {T}`, `@type`, `@typedef`, `@template` ...; see `keep_jsdoc_types`) | `// @ts-ignore`, `@ts-expect-error`, `@ts-check`, `eslint-disable`, `/// <reference>`, `@flow`, `//# sourceMappingURL`, `/*! */`, `@license`, `@preserve`, the `#!` line |
| Shell (`shell`, aliases `sh`, `bash`, `zsh`) | `#` at the start of a word | none | `#!` lines, `# shellcheck`, `# shfmt`, modelines |
| SQL | `--`, `/* */` (nests) | none | `/*+ hints */`, `/*!40101 ... */` (MySQL runs it), `-- +goose`, `-- migrate:`, `-- name:` (sqlc), `-- noqa`, `-- sqlfluff:` |

Comment markers inside strings, raw strings (`R"x(...)x"`, `r#"..."#`, Go backticks), Java text blocks and char literals are
not comments. A text that starts inside a block comment (a stray `*/`), ends inside one, or has a string that never closes
is refused.

**JavaScript and TypeScript.** A `/` is a division or a regex literal depending on the previous token, as in a parser; right
after `}` it cannot be told, so the text is refused. Regex literals (with `[/]` classes), template literals with nested
`${ }` and the `#!` line are skipped. A comment or `/` inside a `${ }` expression is refused, and so is JSX, or a `<Tag` where
an expression starts (this also refuses TypeScript's angle-bracket assertion `<T>x`).

**Shell.** `#` is a comment only at the start of a word, so `${#x}`, `$#`, `${x#p}`, `16#ff` and `a#b` are code. Quotes,
`$'...'`, backticks, `$( )`/`${ }` inside double quotes and here-documents (`<<EOF`, `<<-EOF`, `<<'EOF'`) are skipped; a `#`
in a heredoc body is content. A comment inside `"$( ... )"` is skipped with the string, so it stays. A text with a markdown
fence is refused. **Shell is not part of `"auto"`**: a window that starts inside a heredoc body looks like code, and its `#`
lines would be hidden. Enable it by name.

**SQL.** `''` and `""` escapes, backtick identifiers and Postgres `$tag$ ... $tag$` quotes are skipped. Refused: a string whose
closing quote follows a backslash (MySQL and `E'..'` read it as an escape, standard SQL does not), a MySQL `# comment`,
and an unterminated string or dollar quote.

## How it composes with `tool_output_cap`

Pruning runs first, in the crossing hook, so the cap measures the text the agent will actually receive. The rewrite is left
on `controls.shaped_result`; the host applies it with `controls.take_shaped_result()` (the same one-shot pattern as
`take_tool_result()`). A host that never calls it is unaffected.

## Params

| param | default | meaning |
|---|---|---|
| `comments` | `true` | hide comments |
| `docstrings` | `true` | hide docstrings |
| `min_saved_chars` | `200` | leave the result alone unless it saves at least this many characters beyond the note |
| `languages` | `["python"]` | languages to prune: any of `python`, `go`, `java`, `rust`, `c` (alias `cpp`), `js` (aliases `ts`, `javascript`, `typescript`), `shell` (`sh`, `bash`, `zsh`), `sql`, or `"auto"` for all of them except `shell`. An unknown name is an error |
| `keep_jsdoc_types` | `true` | keep a JSDoc block that has a type tag (plain JavaScript uses them for `tsc --checkJs`); `false` hides it too, which is right for TypeScript |

## Limits

- Only the enabled languages (Python by default). PHP and Ruby are not supported.
- Go, Java, Rust, C/C++, JS/TS, shell and SQL have lexeme parity tests and fragment tests but **no replay or live evidence yet**; that is why
  they are not on by default (design section 5.6).
- A text that starts or ends inside a docstring is either refused (it does not tokenize cleanly) or pruned only where a
  docstring is provable; code lines are never changed.
- Hiding explanations can make an agent re-read or misjudge a function. Whether it helps is measured, not assumed.

## Status

Implemented and unit tested. Not part of the default seed.
