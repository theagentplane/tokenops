# 0009. Ship a Claude Code plugin from this repository, priced from the framework price book

| Field | Value |
|---|---|
| Status | Proposed |
| Date | 2026-11-26 |
| Deciders | Tisha Chawla, Susheem Koul |

## Context

Many Claude Code users hit their plan's usage limit and do not know why. Their session
transcripts (`~/.claude/projects/*/*.jsonl`) record every response's usage, including cache
reads and the two kinds of cache write, so the answer is on their machine. Popular token savers
(caveman, RTK) promise savings, but they only shrink output or shell output; on our own
sessions, re-buying the cache after a break and re-reading context were most of the usage.

TokenOps governs calls from inside an agent's process. Claude Code is a closed agent: the only
ways in are its plugin hooks (`SessionStart`, `PreToolUse`, `PostToolUse`, `SessionEnd`) and
its transcripts. A plugin installs in two commands (`/plugin marketplace add`, `/plugin install`).

## Options considered

### Option A: a plugin in this repository, standard-library Python, prices from the price book

`integrations/claude-code/` holds the plugin; `.claude-plugin/marketplace.json` at the repository
root lets users add this repository as a marketplace. Its prices are a JSON file generated from
`tokenops.framework.pricing.DEFAULT_RATES` and checked by a test, so there is one price source.

- Good: one repository and one brand; users install nothing with pip; the hooks start fast.
- Bad: the plugin cannot import the framework at runtime (Claude Code copies only the plugin
  folder), so its transcript reader and cost arithmetic are small standalone code.

### Option B: a plugin that depends on the `agent-tokenops` package

- Good: reuses the framework directly.
- Bad: every user needs a matching Python package installed before the hooks work, and a
  missing or old package breaks the plugin. Most Claude Code users do not manage Python packages.

### Option C: a separate repository

- Good: no rules or release cycle shared with the SDK.
- Bad: a second brand and a second price table to keep in sync.

## Decision

We will ship the plugin as Option A: in `integrations/claude-code/`, standard library only,
reading transcripts and plugin hook payloads, with prices generated from the framework's price
book. Its hooks fail open (any error exits quietly and Claude Code carries on) and its data stays
on the user's machine.

## Consequences

- **Good:** two-command install; the price book now has to be right for Claude, which also fixes
  the SDK's Claude prices.
- **Bad or risky:** a second small reader of usage data next to `framework/usage.py`; the
  transcript format is Claude Code's, not a public contract, and may change. `Usage` has no
  cache-write bucket, so the plugin prices cache writes from `CACHE_WRITE_5M`/`CACHE_WRITE_1H`
  while the governor does not yet.
- **Follow-ups:** the plugin pull requests (`/tokenops:doctor`; then report, budget and hooks);
  a cache-write bucket in `Usage`.

## Impact on other repositories

None. The plugin reads Claude Code's local files and does not use the control plane.

## Links

[Claude Code plugins reference](https://code.claude.com/docs/en/plugins-reference) ·
[hooks reference](https://code.claude.com/docs/en/hooks)
