# concurrency_cap — infra shield (not a cost lever)

Companion to the policies LLD and `halt.md`.

Code: `tokenops-dev/src/tokenops/control/policies/concurrency_cap.py`
Tests: `tokenops-dev/tests/test_concurrency_cap.py`

---

## TL;DR

Bounds how many calls for a segment run **at once**, to protect memory and downstream rate
limits. At **pre_call**, if in-flight calls have hit the ceiling, the action is **QUEUE**
(single process — backpressure) or **REJECT** (distributed — retryable 429). It never
kills admitted work and saves no tokens — it is an *infrastructure* control, not a budget.

## Detect (formula)

```
inflight(seg) ≥ max_concurrent
```
`seg` is `segment_key_for(attr, dimension, tag_key)` — defaults to the run, but can scope
to tenant/agent/tag. `inflight` is the admit/complete counter (incremented when a call
starts, decremented when it returns).

## Action it takes to govern — QUEUE or REJECT

| Deployment | Action | Why |
|---|---|---|
| single process | **QUEUE** (`retry_after_s`) | hold in a bounded semaphore; backpressure the caller |
| serverless / distributed | **REJECT** (429, `retry_after_s`) | never hold an open request across a scalable container; the caller's backoff resubmits |

Both are **backpressure on starting new work** — the calls already admitted keep running.
Cancelling admitted work would waste tokens for no saving, so it is explicitly forbidden.

## Why not a cost lever

Concurrency bounds *parallelism*, not *spend*. Ten serial calls cost the same as ten
parallel ones. Use `cost_budget` / `pre_call_worst_case` for spend; use this only to keep
memory and downstream limits safe.

## I/O & success criteria (test contract)

| Input (FakeView) | Expect |
|---|---|
| `inflight = max` | `TRIP` → QUEUE or REJECT (per mode) |
| `inflight = max − 1` | `None` (ALLOW) |
| mode="reject" | `Action(REJECT, retry_after_s)` |
| mode="queue" | `Action(QUEUE)` |

## Status

✅ implemented, ✅ tested (unit). e2e admit/complete wiring (incrementing `inflight` around
real calls) lands with the provider wrap in Phase 5.
