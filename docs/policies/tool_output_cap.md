# tool_output_cap — keep a giant tool payload out of context

Companion to `halt.md`. Strong, always-on.

Code: `tokenops-dev/src/tokenops/control/policies/tool_output_cap.py`
Tests: `tokenops-dev/tests/test_tool_output_cap.py`

---

## TL;DR

A tool returns a huge blob (a 40k-row dump); feeding it back to the model next turn is the
expensive part. The action is **INJECT** — offload the full payload behind a handle and
substitute a small descriptor `{size, count, handle}` plus an instruction to paginate or
filter. Never HALT; never feed back a sliced payload as if it were whole.

## Detect (formula)

```
est_tokens = len(payload) / divisor ;   trip if est_tokens ≥ cap
divisor = 4    for natural-language text
divisor = 2.8  for JSON / structured / code   (denser tokenization; also the default for
               unknown content, so a large payload is never under-counted)
```
Cheap `len()` — no tokenizer on the hot path. The auxiliary cost is negligible versus
sending the blob to the model.

## Action it takes to govern — INJECT a descriptor

1. Compute `est_tokens`; if `≥ cap`, emit `WARN`.
2. Policy substitutes the payload with a message:
   `TOOL OUTPUT OFFLOADED: ~N tokens, count=…, handle=store://… — paginate or filter via the handle`.
3. The full payload lives behind `handle` (a store reference), retrievable in slices — the
   model asks for what it needs instead of swallowing everything.

## Why content-aware divisor

JSON/code tokenize denser than prose (more tokens per character), so the *same byte length*
is *more tokens* when structured. Using `/2.8` for structured (and as the default) means we
never under-count and let a big payload slip through.

## I/O & success criteria (test contract)

| Input | Expect |
|---|---|
| large structured dict, cap 100 | `WARN` → INJECT with `handle=store://…` |
| small result `{snippet, completeness}`, cap 8000 | `None` |
| same-length text vs json | json estimates more tokens (smaller divisor) |
| `node_type="llm"` | `None` (tool-only) |

## Status

✅ implemented, ✅ tested (unit + e2e). Descriptor substitution is **live**:
`Action.replace_tool_result` → the research agent's `take_tool_result()` swaps the oversized
payload for the descriptor in context. The handle here is a content hash (real store offload
is a later refinement).
