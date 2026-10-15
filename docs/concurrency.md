# Concurrency contract

TokenOps is designed for **many concurrent runs in one process** (threads, or asyncio tasks that
hop to worker threads) and for **many processes sharing one control plane**.

A shared long-lived `Governor` for many runs is out of scope; the usual pattern is one
`Governor` per hop (`tokenops_run`) plus request-local contextvars.

## Summary

| Surface | Same process, many threads | Different processes |
|---|---|---|
| `Ledger` (one instance) | Safe: in-memory maps are serialized on an `RLock` | n/a (not shared) |
| `Ledger` with a control plane | Safe for spend, in-flight and halt across Ledgers/Governors | Shared through the plane |
| `ControlPlaneClient` | Safe: `httpx.Client` plus a lock around the governance cache | Per-process governance cache |
| `LedgerEventWriter` | Safe: a queue with one worker thread; `submit` never blocks | Per-process queue |
| contextvars / request dims | Task and request local, not mutex-protected | n/a |

## Different traces vs the same trace

**Different `trace_id`s** on one `Ledger`: concurrent `record`, `admit`/`complete` and spend
updates must not lose increments. Tests cover this (`tests/test_thread_safety.py`).

**The same `trace_id`**: mutations serialize on the Ledger. Halt flags (`mark_halted`,
`is_halted`) are not torn. Prefer one logical writer per trace; concurrent writers are correct
but ordered arbitrarily.

## Writes and reads with a control plane

- `admit` and `halt_mark`/`halt_clear` are written synchronously: other processes gate on them.
- `spent_add` and `complete` are queued and sent in order from a background thread
  ([ADR 0003](adr/0003-ledger-spend-writes-are-asynchronous.md)).
- A read of shared state first waits (bounded, 2 s) for this process's own queued writes, so a
  process always sees its own spend. Other processes see it after the queue delay.
- A write is attempted once and never retried when its outcome is unknown, because the plane does
  not deduplicate events ([ADR 0002](adr/0002-ledger-writes-are-attempted-once.md)).

## What is not claimed

- Lock-free hot paths: correctness uses coarse locks.
- Asyncio: do not `await` while holding a ledger lock; the APIs are synchronous.
- A shared step window across processes: the window is per process and per trace
  ([ADR 0004](adr/0004-policy-state-lives-in-process-except-shared-spend.md)).

## Modules

- `tokenops.control.ledger`: `Ledger._lock` around the in-memory maps.
- `tokenops.repositories.control_plane_client`: governance cache lock.
- `tokenops.repositories.ledger_event_writer`: the queue and the worker thread.
