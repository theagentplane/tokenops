# tool_fix — cheap defensive check for hallucinated tool calls

Companion to `halt.md`.

Code: `tokenops-dev/src/tokenops/control/policies/tool_fix.py`
Tests: `tokenops-dev/tests/test_tool_fix.py`

---

## TL;DR

Catches a bad tool call (unknown name or invalid args) **before** the model burns an I/O
round-trip, and breaks the loop if the model keeps repeating it. The action is **INJECT** a
synthetic error result so the model self-corrects; after **K identical failures** it gives
up and **HALT**s.

## Detect (formula)

```
name ∉ registry  (O(1) hash)   OR   ¬valid(args, schema[name]) ;   track fails(run)
```
`registry` is the set of real tool names; `schema[name].required` lists required args. The
detector keeps a **per-run counter of identical failing names** (the first stateful
detector) — `reset(run_id)` clears it.

## Action it takes to govern — INJECT, then HALT after K

| Condition | Severity | Action |
|---|---|---|
| invalid call, attempt `< K` | `WARN` | **INJECT** `{error, did_you_mean, available_tools}` instead of executing |
| same invalid name, attempt `≥ K` | `TRIP` | **HALT** — the model is stuck in a bad-call loop |

`did_you_mean` is the closest registry name by **edit distance** (only suggested if it's a
plausible typo). The injected result is a normal tool-result message, so the model treats
it as feedback and corrects on the next turn — no execution happened.

## Edge cases

* A **valid** call → `None` (ALLOW), executes normally.
* Counter is keyed by the **offending name** per run, so two *different* bad names don't
  prematurely trip the K threshold.
* Args validation is minimal (required-keys present); richer JSON-schema checks slot into
  `_invalid` without changing the action.

## I/O & success criteria (test contract)

| Input | Expect |
|---|---|
| `name="search"` (valid) | `None` |
| `name="serch"` | `WARN` → INJECT, `did_you_mean="search"` |
| `name="serch"` ×3, K=3 | `warn, warn, trip` → HALT on the 3rd |
| `name="search"`, missing required `q` | `WARN` (`problem="missing_args:['q']"`) |

## Status

✅ implemented, ✅ tested (unit). INJECT application (feeding the synthetic result into the
next input) is honoured by the provider wrap in Phase 5.
