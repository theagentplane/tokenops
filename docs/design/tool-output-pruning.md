# Design: tool output pruning for coding agents

| Field | Value |
|---|---|
| Status | Proposed |
| Date | 2026-11-07 |
| Policy | [`tool_output_prune`](../policies/tool_output_prune.md) (Python proof of concept, opt-in, on branch `feature/tool-output-pruner`) |
| Related | [#190](https://github.com/theagentplane/tokenops/issues/190) (nothing applies a tool-result change today), [`tool_output_cap`](../policies/tool_output_cap.md) |
| Evidence | benchmark repo `tokenops-benchmarking`: `swebench-verified/runs_prune/` (live run), `miniswe/replay_prune.py` (replay) |

## 1. Summary

A coding agent spends a large share of its input tokens on tool results that are source code, and a large part of
that source is comments and docstrings. The proposal is a policy that **rewrites a source-code tool result so that
comments and docstrings are hidden**, keeping every code line verbatim and the line count unchanged. It works from the
result text alone.

The Python proof of concept exists and is measured. A deterministic replay over 50 recorded runs says it would have
cost **6.1% less** with the agent's behaviour held fixed. A live A/B of 50 pairs could **neither confirm nor rule out**
that saving (cost ratio 1.08, 95% interval 0.91 to 1.26), because agent-to-agent noise is larger than the effect.
Before generalising, this document asks for agreement on (a) the method of evidence, (b) the safety contract, and
(c) how other languages are supported.

## 2. Problem

`tool_output_cap` looks at the size of a tool output and cuts it. It has no basis to judge whether the part it cuts
is the part the agent needs, so a wrong cut costs the agent extra calls and extra tokens. We wanted a reduction that is
principled: remove content that is rarely needed to make an edit, and never touch what is.

Comments and docstrings are the obvious candidate. In the benchmark's tool outputs, about 20 to 30% of the tokens of a
Python source view are comments and docstrings. They do not change what an edit has to match.

## 3. Proposal

### 3.1 Behaviour

For a tool result that is recognised as source code:

- A comment becomes empty (whole-line) or is trimmed (trailing).
- A docstring or doc comment the policy can prove is one becomes a one-line placeholder plus blank lines.
- Everything else is unchanged, byte for byte, **including the number of lines**, so line numbers the agent has seen
  or will cite still hold and exact-text edits still match.
- A one-line note is appended telling the agent how to get a hidden line back (`grep -n`).
- Comments that tools read stay (see 3.3).

The policy never HALTs, never drops code, never needs the command that produced the text.

### 3.2 Where it sits

The policy shapes the result *before* `tool_output_cap` measures it, so the cap sees the pruned size. The wrapped tool's
own return value is not changed (Chronicle's `crossing` hook is observe-only, see #190): the shaped text is exposed
through `Governor.shape_tool_result` and `ApplyControls.take_shaped_result()`, and the **agent adapter splices it in**.
That is the same adapter obligation #190 describes for `take_tool_result()`. If #190 lands a framework-level way to
replace a result, `tool_output_prune` should use it and the adapter hook goes away.

### 3.3 Safety contract (applies to every language)

1. **Never change a code token.** Compare the sequence of code lexemes (comments and whitespace removed) before and
   after. If they differ, return the text untouched. For Python, when the whole text parses, the syntax tree minus
   docstrings must be equal.
2. **Keep the line count.** A hidden block becomes blank lines.
3. **Refuse when unsure.** Not source code, does not lex cleanly, ambiguous language, error tokens, saves less than
   `min_saved_chars` after the note: return the text as it is.
4. **Keep comments that carry meaning to a tool or to the compiler** (per-language list in section 5).
5. **Fragments are normal.** A `sed -n` range can start inside a block comment or end inside a string. Handle the cases
   that are provable (a text that ends inside a docstring that started at a statement boundary) and refuse the rest.
6. **No LLM, no network, deterministic.** Same text in, same text out.

## 4. Evidence and methodology

### 4.1 What we need to know

Two different questions, which need different instruments:

| Question | Instrument |
|---|---|
| How many tokens, and how much money, does hiding comments and docstrings remove from the same run? | deterministic replay |
| Does the agent behave differently (more re-reads, more calls, fewer fixes) when explanations are hidden? | live A/B |

### 4.2 Why a live A/B alone cannot answer the first question

The agent is not reproducible: the benchmark sets no seed and no temperature, and `gpt-5-mini` is a reasoning model that
uses the provider's default sampling. We measured how much a single run varies, on the same 25 instances, 2 repeats each:

| Pairing (same instance) | pairs | sd of log(cost ratio) | 95% interval on the sd |
|---|---|---|---|
| vanilla r1 vs vanilla r2 (no TokenOps) | 25 | 0.46 | 0.31 to 0.58 |
| tokenops r1 vs tokenops r2 (prune on) | 25 | 0.66 | 0.34 to 0.91 |
| vanilla vs tokenops, same repeat | 50 | 0.53 | 0.38 to 0.68 |

An sd of 0.46 means two vanilla runs of the same task routinely differ by about 1.6 times. The comparison is
indistinguishable from baseline noise. Pairs are also not independent (two repeats of one instance share its
difficulty), so the effective sample is nearer 25. With this noise, detecting a 10% saving at 80% power needs about 200
pairs on an optimistic estimate and a 5% saving about 830. That is hours of runs per experiment for a result that is
still ambiguous.

### 4.3 Why a replay

The policy changes one thing: the text of tool messages. If we hold the agent's decisions fixed, which a recorded
trajectory does, the effect on cost is a deterministic function of recorded data. So:

1. Take a recorded **vanilla** trajectory. Each tool message stores `raw_output`, the full output of the command.
2. Send each `raw_output` through the real TokenOps path (`GovernedLitellmModel` plus the governed environment with the
   actual `tool_output_prune` policy), then render it with the benchmark's own observation template (which also applies
   mini-swe-agent's 10,000-character truncation, so the pruned text is truncated exactly as in a live run).
3. Re-price the run. Every call's input is the recorded prompt-token count, minus the token difference of all earlier
   tool messages (original versus pruned, counted with `tiktoken` o200k). The cached share of each prompt is kept at the
   recorded hit rate (rounded down to 128 tokens) and billed at the cached price; completion tokens are kept as
   recorded. Prices are those of `gpt-5-mini`: $0.25 / $0.025 cached / $2 per million tokens.

There is no model call, so there is no sampling noise, it costs nothing, and variants (comments only, docstrings only,
different thresholds, future languages) are priced in seconds on the same 50 runs.

### 4.4 Validation of the replay

- The observation re-rendered from `raw_output` with the original text equals the recorded message in **1,422 of 1,422**
  tool messages.
- The model reproduces the recorded vanilla cost to within 1.7% ($2.216 modelled, $2.255 recorded).

### 4.5 Replay results (50 vanilla runs, PASS_E25, `azure/gpt-5-mini`)

| Setting | Tool outputs changed | Input tokens, summed over calls | Cost |
|---|---|---|---|
| comments + docstrings (proposed default) | 384 of 1,422 (all 50 runs) | 26.6M to 23.8M (10.4% fewer) | $2.216 to $2.081 (**6.1% lower**) |
| docstrings only | 270 | 6.4% fewer | 3.5% lower |
| comments only | 283 | 3.0% fewer | 1.1% lower |

Per run, for the proposed default: median saving 5.5%, range 1.1% to 15.5%, more than 5% in 26 of 50 runs. Docstrings
carry most of the saving. Hiding comments alone can cost a run slightly (the note line adds tokens). The token saving
is larger than the cost saving because most of a prompt is billed at the cached price.

### 4.6 Live A/B results (same 25 instances, 2 repeats, 50 pairs)

| | vanilla | prune on | ratio |
|---|---|---|---|
| Cost | $2.25 | $2.43 | 1.079 (95% 0.91 to 1.26) |
| API calls | 1,494 | 1,659 | 1.11 |
| Re-views of an already viewed file | 352 | 413 | 1.17 |
| Resolved | 29 of 50 | 30 of 50 | about equal |

Pruning fired in all 50 runs (388 times). The extra cost is concentrated in a few runs (the three largest increases
add $0.30 against a net of $0.18), the same instance (`sympy__sympy-22714`) moved in opposite directions in its two
repeats, and the call-count spread between prune and vanilla matches the spread between two vanilla repeats (median 6.5
against 6.0). The honest reading is: **no loss in quality, no demonstrated saving, and a possible increase in re-reads
that the sample cannot confirm or exclude.** Per-call context fell about 3% live against about 10% in the replay, which
is consistent with the agent reading more when explanations are hidden, but is not proof.

### 4.7 What the two instruments do not tell us

- The replay assumes the agent issues the same commands. It is an upper bound on the saving if behaviour changes.
- The live run measures behaviour but is too noisy at this size to measure a 6% effect.
- Only the PASS_E25 slice (the 25 costliest tasks the reference run resolved), one model, Python only.
- Pruning is replayable; policies that change behaviour (`progress_guard`, `cost_guard`) are not.

### 4.8 Experiment plan

1. Replay on the **prune-arm** trajectories to measure how much of the replayed saving was spent on extra calls (the
   behavioural cost, directly).
2. A larger live run drawn from `ALL` or a random slice (not the expensive tail), sized from the measured noise.
3. A behavioural probe that does not need many runs: for each pruned view, did the next command re-read the same file
   range, or `grep -n` it?
4. Ablations by replay, then confirmed live only for the winners: keep the first line of each docstring, keep comments
   marked `TODO`/`FIXME`/`HACK`/`NOTE`, hide docstrings only.

## 5. Other languages

The Python implementation is a hand-written lexer on the standard library. The approach generalises, but the hazards are
language-specific, so each language needs its own rules and its own evidence.

### 5.1 Why Python-only is a real limit

SWE-bench Verified is Python. Agents in the field read Java, TypeScript, Go, Rust, C and C++, Ruby, PHP and shell too.
Public multilingual variants exist (for example SWE-bench Multilingual and Multi-SWE-bench); their language mix should
be confirmed before choosing the first target after Python.

### 5.2 Per language: what a comment is, what a doc comment is, what must stay

| Language | Comments | Doc comments | Must stay, or needs a decision |
|---|---|---|---|
| Python | `#` | docstring: first statement of a module, class or function | `# type:`, `# noqa`, `# pragma`, `# fmt:`, `# pylint:`, `# mypy`, shebang, `# -*- coding -*-`. Docstrings containing doctests (`>>>`) are tests: decide whether to keep them |
| JavaScript / TypeScript | `//`, `/* */` | JSDoc `/** */` | `// @ts-ignore`, `@ts-expect-error`, `// eslint-disable`, `/// <reference>`, `// @flow`, `/*! license */`, `//# sourceMappingURL`. JSDoc carries types in JavaScript (`@param {T}`), so hiding it removes type information |
| Java / Kotlin / C# | `//`, `/* */` | Javadoc, KDoc, `///` XML doc | `@SuppressWarnings`-style annotations are code, not comments (safe). `//noinspection`. License header handling |
| Go | `//`, `/* */` | comment block directly above a declaration | `//go:build`, `//go:generate`, `//go:embed`, `//nolint`, **the `/* */` preamble above `import "C"` is code (cgo)**. Doc comments are the main readable description of an exported symbol |
| Rust | `//`, `/* */` (nests) | `///`, `//!`, `/** */` | `// SAFETY:` (decide), `#[doc]` is an attribute (code). Block comments nest, so a naive `*/` search is wrong |
| C / C++ | `//`, `/* */` | Doxygen `/** */`, `///` | `#pragma`, `/* fallthrough */` style markers, `#if 0` blocks (dead code, not comments), license headers. Comment markers inside strings and raw strings, line continuation with a backslash in a `//` comment |
| Ruby | `#`, `=begin ... =end` | YARD comments | `# frozen_string_literal:`, `# encoding:`, `# rubocop:`. Heredocs may contain `#` |
| PHP | `//`, `#`, `/* */` | PHPDoc `/** */` | PHPDoc **annotations are read by frameworks** (`@ORM\Column`, `@Route`): keep annotation lines |
| Shell | `#` | none | shebang, `# shellcheck`. `#` inside heredocs, quotes and `${#var}` is not a comment |
| SQL | `--`, `/* */` | none | optimiser hints `/*+ ... */`, `--` inside strings |

Out of scope for pruning: data and markup (JSON, YAML, TOML, Markdown, logs). A `#` there is content, not a comment.

### 5.3 Detecting the language from the text alone

The policy does not know the command or file name. It scores a text against each enabled language handler by structure
(keywords at line starts, brace and semicolon shape, `package`/`import`/`use`/`#include` lines, shebang), requires a
minimum number of structure lines, and **refuses when the top two scores are close**. Generic exclusions stay shared:
diffs, `grep -n` hit lists, numbered listings and test reports are never pruned, in any language. When an adapter can
cheaply give a hint (the file extension in the command), a handler may use it to break ties, but correctness must not
depend on it.

### 5.4 Engine options

| Option | What it is | Good | Bad |
|---|---|---|---|
| A. Hand-written lexer per language (as today for Python) | standard library only | no dependency, exact control, fast | each language is real work; JavaScript regex literals and template strings are hard to lex by hand |
| B. Shared lexers for families | one C-style lexer (`//`, `/* */`, string and char forms, optional nesting) and one hash-style lexer, parameterised per language | covers about eight languages for the cost of two | still needs per-language string and doc rules |
| C. tree-sitter | one engine, one grammar per language, error recovery on fragments | handles JS/TS and Rust correctly, gives code-lexeme equality for free, distinguishes doc comments | binary dependency (wheels per platform), grammar versions to track, error nodes on fragments need the same refuse logic |
| D. Regular expressions | | | unsafe: strings and comments interleave; rejected |

**Recommendation:** keep the Python handler (A). Add B for the C-style and hash-style families behind a `LanguageHandler`
interface. Offer C as an optional extra (`tokenops[prune-multilang]`) used only where B cannot be correct, in
particular JavaScript and TypeScript. TokenOps core stays dependency-free.

### 5.5 Interface and configuration

```
class LanguageHandler(Protocol):
    name: str
    def score(self, text: str) -> float: ...          # 0 when not this language
    def spans(self, text: str) -> list[Span] | None:  # comment and docstring spans, or None to refuse
    def keep(self, span: Span) -> bool: ...           # significant comments and annotations
    def same_code(self, before: str, after: str) -> bool: ...   # lexeme equality for the safety contract
```

```
"tool_output_prune": {
  "languages": ["python"],          // default: python only. "auto" enables every installed handler
  "comments": true, "docstrings": true,
  "min_saved_chars": 200
}
```

The shared driver owns detection exclusions, the line-count-preserving rewrite, the note, the minimum-saving rule and the
safety contract; a handler only finds spans.

### 5.6 Evidence needed before enabling a language

A language is enabled by default only when all of these hold:

1. **Parity:** on real tool outputs the code-lexeme sequence is identical before and after, with zero mismatches.
2. **Coverage:** the share of source views the handler accepts (Python: 261 of 533 on the first real sample).
3. **Replay:** a deterministic replay on recorded trajectories in that language shows a token saving worth the
   behavioural risk. This needs recorded runs in that language, so the first step is a run on a multilingual benchmark.
4. **Behaviour:** a live run with enough pairs to bound the re-read and call increase.

## 6. Risks

- **The agent re-reads more.** The one worrying signal in the live data. Mitigations to test: keep the first line of
  docstrings; keep `TODO`/`FIXME`-style comments; docstrings only.
- **A hidden comment was the explanation the agent needed.** The note tells it how to recover a line; the live run saw no
  rise in `grep -n` (157 against 161), so the recovery path is not being used much.
- **A hidden doc comment is a contract in some languages** (Go exported symbols, PHPDoc annotations). Per-language `keep`
  rules and the default of Python only.
- **A language handler corrupts code.** The lexeme-equality check turns this into "no change" instead of a wrong edit.
- **Adapter dependency.** Same as #190: until a framework-level result replacement exists, each adapter splices the shaped
  text in.

## 7. Alternatives considered

- **A size cap only (`tool_output_cap`).** No basis to choose what to cut; measured to add calls after cuts.
- **A decision model that scores chunks for relevance.** Costs a call per output and adds its own noise; not tried.
- **Schema-based field projection for structured (MCP) outputs.** Sound but a different problem and likely a small
  saving for coding agents; separate proposal.
- **Stop-word removal and minification of text.** Unsafe for code, small for prose, rejected.
- **Whitespace and indentation squeezing.** Breaks exact-text edits and Python semantics; rejected.

## 8. Open questions

1. Should the policy live behind the same result-replacement mechanism as #190, and who owns it?
2. Is Python-only acceptable as the default for the first release, with languages added one at a time under 5.6?
3. Keep doctests visible?
4. tree-sitter as an optional extra: acceptable for packaging?
5. What is the minimum evidence bar for turning the policy on by default, given a live A/B at this noise level needs
   hundreds of pairs?

## 9. Reproducing the measurements

In the benchmark repo (`tokenops-benchmarking`):

```bash
cd swebench-verified/agents/mini-swe-agent
PYTHONPATH=. .venv/Scripts/python.exe miniswe/replay_prune.py ../../runs_prune/mini-swe-agent/gpt-5-mini/PASS_E25
```

The raw trajectories are not committed (see the benchmark's `results/README.md`).
