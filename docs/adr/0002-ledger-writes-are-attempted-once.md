# 0002. Attempt each ledger write once; never retry an unknown outcome

| Field | Value |
|---|---|
| Status | Proposed |
| Date | 2026-10-15 |
| Deciders | Susheem Koul, Tisha Chawla |

## Context

TokenOps writes spend, in-flight and halt events to the control plane's ledger
(`POST /v1/ledger/events:batch`). The plane applies a batch in order in one transaction and does
**not** deduplicate events (control-plane ADR 0007): a batch applied twice counts twice. A write
whose response is lost (timeout, reset after the request was sent) leaves the client unable to
know whether it was applied. Issue 162 asks that this policy be decided and documented.

## Options considered

### Option A: retry on any failure

- Good: a transient network error does not lose an event.
- Bad: an applied-but-unacknowledged batch is counted twice, so a budget trips early and spend
  is overstated.

### Option B: attempt once, never retry, report the failure to the caller

- Good: spend is never overstated by the client.
- Bad: an event can be lost, so spend can be understated by the events of a failed write.

### Option C: retry only when the request provably never reached the server

- Good: no double count, and a refused connection loses nothing.
- Bad: a small amount of retry logic; "provably" must be limited to connection failures before
  any bytes are sent.

## Decision

The client attempts each write **once** (Option B). A caller that wants more (a background writer
in a later change) may retry only when the request provably did not reach the plane (a failed
connect), which is Option C layered on top. An unknown outcome is never retried.

## Consequences

- **Good:** the ledger never double counts because of the client.
- **Bad or risky:** a lost write understates spend; budgets are enforced on what the plane saw.
  The caller must count and surface failed writes.
- **Follow-ups:** the asynchronous batching writer (next component) implements Option C and
  exposes a dropped-event counter.

## Impact on other repositories

control-plane: none (it already documents that events are not deduplicated).

## Links

- control-plane ADR 0007, `docs/governance-api.md`
- Issue 162, section 2
