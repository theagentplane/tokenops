# progress_guard — the last-resort unstick

Companion to `halt.md`. Default.

Code: `tokenops-dev/src/tokenops/control/policies/progress_guard.py`
Tests: `tokenops-dev/tests/test_progress_guard.py`

---

## TL;DR

Detects a run that is spinning — repeating the same action with the same result, or emitting
near-identical model output. The action is **INJECT** a deterministic "you're stuck, change
approach" correction; only after **K corrections with no progress** does it **HALT**.

## Detect (formula) — Tier 1, in-path, deterministic

```
exact repeat:  count in recent(run,W) of (signature, result_hash) ≥ K     (tool)
near-dup:      SimHash(output.text) within Hamming threshold of recent     (llm)
hang:          now − last step ts > T                                      (tick, future)
```
**The discriminator:** an unchanged *result* (`signature` AND `result_hash` both equal), not
merely a repeated *call*. A repeated call that returns something *new* is progress and does
not trip — this is what stops false positives on legitimate retries.

## Action it takes to govern — INJECT, then HALT after K corrections

| Condition | Severity | Action |
|---|---|---|
| stalled, corrections `≤ max_corrections` | `WARN` | **INJECT** a factual "no progress; change approach or finalize" message |
| stalled, corrections `> max_corrections` | `TRIP` | **HALT** — corrections didn't help |

A per-run **correction counter** (stateful detector) escalates WARN→TRIP. The injected
message is pinned by `context_compaction` so it survives prompt trimming.

## Tier 2 (off-path, optional)

Embedding semantic similarity, sampled/async — feeds the dashboard, never the in-path stop.
Not implemented; the in-path stop is Tier 1 only (deterministic, no model).

## I/O & success criteria (test contract)

| Input | Expect |
|---|---|
| same `signature`, **different** `result_hash` | `None` (progress) |
| same `(signature, result_hash)` ×K, then more | `WARN→INJECT`, escalating to `TRIP→HALT` |
| 3 near-identical llm `output.text` (SimHash) | `WARN` |

## Status

✅ implemented, ✅ tested (unit). Tier-1 exact-repeat + SimHash done; hang-via-tick and
Tier-2 embeddings are future. INJECT application lands with the provider wrap (Phase 5).
