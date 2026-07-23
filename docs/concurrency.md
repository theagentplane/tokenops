# Concurrency contract

TokenOps is designed for **many concurrent runs in one process** (threads or asyncio
tasks that hop to worker threads). Guarantees below are for the shared control-plane
state: `Store`, `Ledger`, and the governance config cache.

`GovernorContainer` / shared Governor re-entrancy across the same `run_id` is a later
wave (§11); today’s usual pattern remains **per-request Governor** + request-local
contextvars.

## Summary

| Surface | Same process, many threads | Different processes |
|---|---|---|
| `Store` (one instance) | Safe — DB ops serialized on an RLock | Safe for ledger spend/inflight/halt via WAL + atomic SQL (each process opens its own connection) |
| `Ledger` (in-memory) | Safe — maps serialized on an RLock | N/A (not shared) |
| `Ledger` + shared `Store` | Safe for spend/inflight/halt across Ledgers/Governors | Same as Store |
| Governance config cache | Safe — process Lock on get/set/invalidate | Per-process cache (not shared) |
| contextvars / request dims | Task/request local — not mutex-protected | N/A |

## Different `run_id` vs same `run_id`

**Different `run_id`s** on one `Ledger` / one `Store`: concurrent `record`, `admit` /
`complete`, and ledger spend updates must not lose increments. Tests cover this.

**Same `run_id`**: mutations serialize on the Ledger (and Store for persisted halt/spend).
Halt flags (`mark_halted` / `is_halted`) are not torn. Prefer a single logical writer per
run when possible; concurrent writers are correct but ordered arbitrarily.

## What is *not* claimed

- Sharing one `sqlite3` connection across processes (don’t).
- Lock-free / wait-free hot paths — correctness uses coarse RLocks.
- Asyncio: coroutines that call Store/Ledger must not interleave on the same thread
  without await boundaries that release the lock (locks are held only for sync critical
  sections; do not `await` while holding them — current APIs are sync).
- A shared long-lived `Governor` for many runs — out of scope until §11.

## Modules

- `tokenops.control.store` — `Store._lock` (RLock) around DB critical sections
- `tokenops.control.ledger` — `Ledger._lock` around in-memory maps (+ Store for shared state)
- `tokenops.control.governance_cache` — module Lock around the dict
