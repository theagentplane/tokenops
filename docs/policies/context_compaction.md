# context_compaction — keep the prompt lean and cache-friendly

Companion to `halt.md`. Default; needs a hook.

Code: `tokenops-dev/src/tokenops/control/policies/context_compaction.py`
Tests: `tokenops-dev/tests/test_context_compaction.py`

---

## TL;DR

When the assembled input approaches the context ceiling, the action is **MUTATE** the
outgoing prompt — move volatile values below the static prefix (restore the prompt-cache
discount), dedup tool outputs by hash, and summarize only filler while pinning the system
prompt, schema, constraints, and state. Without a prompt-assembly hook it degrades to
telemetry. **Never HALTs.**

## Detect (formula)

```
est_input ≥ ctx_max     OR     est_input rising over recent(run, W)
```
`est_input` ≈ the last llm step's `usage.input` (or `chars/4`) — **never tokenize on the hot
path**. The "rising" arm trips a bit earlier (≥ ctx_max/2 and monotonically increasing
across recent llm steps) so compaction happens *before* the wall, not at it.

## Action it takes to govern — MUTATE the prompt

The MUTATE rewrites the *next* prompt (this is why it fires at **pre_call**):
1. move volatile values below the static prefix → the cached prefix stays a cache hit;
2. dedup repeated tool outputs by hash;
3. summarize only filler; **pin** system prompt, schema, constraints, and live state.

Full history is never lost — it stays in the unbounded ledger window; only the *prompt sent
to the model* is compacted.

## No hook → telemetry, never HALT

Compaction requires a prompt-assembly hook to rewrite the outgoing call. Without one, the
policy emits the signal (for the dashboard) and returns `ALLOW` — it does not, and must not,
HALT: a bloated prompt or a lost cache discount is a cost issue, not a safety stop.

## I/O & success criteria (test contract)

| Input | Expect |
|---|---|
| `est_input = ctx_max` | `WARN` → `MUTATE` |
| `est_input` well below | `None` |
| `est_input ≈ ctx_max/2`, rising across recent llm steps | trips early |
| `has_hook=False` | `ALLOW` (telemetry only) — never HALT |

## Status

✅ implemented, ✅ tested (unit + e2e). The deep prompt rewrite is **live**: `Action.compact`
→ `wrap_complete` rewrites the outgoing messages (dedup non-system, pin system) before
dispatch — no longer just a carry directive.
