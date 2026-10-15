# 0003. Send spend and completion writes in the background; keep admit and halt synchronous

| Field | Value |
|---|---|
| Status | Proposed |
| Date | 2026-10-15 |
| Deciders | Susheem Koul, Tisha Chawla |

## Context

Issue 162 asks that ledger events are batched asynchronously and that the agent path is not
blocked on the write. Every governed LLM call writes at least one event, and a synchronous
round trip per crossing adds latency to each call. The plane applies events in order and does
**not** deduplicate them (control-plane ADR 0007), and ADR 0002 already fixes that a write is
never retried when its outcome is unknown.

Not every write is equal. `spent_add` and `complete` describe something that already
happened. `admit` and `halt_mark` are read by other processes to decide what to do next
(`concurrency_cap`, a shared halt).

## Options considered

### Option A: every write synchronous

- Good: simplest; every write is acknowledged; a halt is visible to everyone at once.
- Bad: one plane round trip per crossing on the agent path.

### Option B: every write in the background

- Good: no agent-path latency from writes.
- Bad: a queued `admit` lets another process exceed a concurrency cap; a queued `halt_mark`
  delays a shared halt.

### Option C: spend and completion in the background, admit and halt synchronous

- Good: removes the latency from the post-call writes, which are the bulk, and keeps the two
  writes other processes gate on immediate.
- Bad: two code paths; spend seen by other processes lags by the queue delay.

## Decision

We will use **Option C**, with a read barrier: before a read of shared spend, in-flight or halt,
the ledger waits (bounded, 2 s by default) for this process's own queued writes, so a process
always sees its own spend. The writer retries a batch only when the request provably never
reached the plane (a failed connect) and never on an unknown outcome (ADR 0002). A full queue
drops new events and counts them; nothing raises into the agent.

## Consequences

- **Good:** the post-call write no longer blocks the agent; reads stay consistent for the
  writing process.
- **Bad or risky:** events can be lost (unreachable plane after retries, unknown outcome, full
  queue), so spend can be understated. `LedgerEventWriter.stats` and an `on_drop` callback make
  every loss visible; a deployment that cannot accept understated spend sets
  `tokenops_run(async_writes=False)`. The trace total on a `BoundaryStep` is the process's own
  running sum, not the plane's cross-process total. Other processes see this process's spend
  after the queue delay.
- **Follow-ups:** surface the drop counters in logs or metrics; a process exit flushes through
  `flush_ledger_writes` (registered with `atexit`).

## Impact on other repositories

control-plane: none.

## Links

- [ADR 0002](0002-ledger-writes-are-attempted-once.md)
- control-plane ADR 0007, `docs/governance-api.md`
- Issue 162, section 2
