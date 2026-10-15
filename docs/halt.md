# HALT: semantics, mid-flight behaviour, and resume

What a halt does to a running agent, why it does not interrupt an in-flight call, and how
work is resumed.

Code: [`framework/engine.py`](../src/tokenops/framework/engine.py) (Governor, controls),
[`framework/ledger.py`](../src/tokenops/framework/ledger.py) (halt flag, window),
[`framework/policies/cost_budget.py`](../src/tokenops/framework/policies/cost_budget.py) (the
canonical HALT producer).

## In short

- A halt stops a run **between boundaries**, never in the middle of a model request.
- The call that breached the budget has **already returned and been counted**. We do not abort
  it: no tokens would be saved.
- A halt **unwinds** the agent loop (raises `Halt`, a `BaseException`); it does not suspend it.
- The flag is set **before** the raise, so a halt is sticky: every later call on the trace is
  refused even if the agent swallowed the exception.
- The halt is a **trace attribute** in the control plane (`tokenops.halted`,
  `tokenops.halt_reason`), so it is visible on `GET /v1/traces/{trace_id}`, in the TokenOps tab
  and to every process on that trace.

## The three points a halt can fire

| Point | When | Already spent | Code |
|---|---|---|---|
| **pre_call** | before a call dispatches | nothing, the call never starts | `Governor.pre_call` |
| **observe** | after a crossing is recorded | the just-finished call | `Governor.observe` |
| **kill switch** | any call on a halted trace | n/a, refused at once | `Governor._refuse_if_halted` |

`cost_budget` (the guarantee) fires at **observe**: it trips when an accumulator crosses its
limit, after the breaching call returned. `pre_call_worst_case` (the prevention) fires at
**pre_call**, so the over-budget call never starts.

## What a halt does not do

When `observe` trips, the call that pushed spend over the limit has already been sent, consumed
tokens, returned, and been priced. Killing it would save nothing and discard a useful result,
so it is kept and the *next* call is refused. The same rule applies to `concurrency_cap`: never
kill admitted work.

The one control that does tear down an in-flight operation is `CANCEL`, used by `wrap_stream` and `output_runaway` to stop a degenerate **stream** that is bleeding tokens; there, stopping mid-flight genuinely saves tokens. There is no suspend (`PAUSE`): a halt unwinds.

## What survives a halt

**In the control plane**, per trace: the halt flag and reason, and the spend accumulators.

**In the process**, until the run scope exits: the step window (every `BoundaryStep` with its
input, output, usage, signature and cumulative spend).

**Lost:** the agent's own local working state. When `Halt` unwinds the stack, locals that were
not checkpointed are gone. Catch `Halt` at the boundary where you can return a partial result.

## How to resume

A halt is terminal by design; resuming is always a deliberate act.

1. **Re-grant, same trace.** Raise the breached limit in the control plane
   (`PUT /v1/budgets`) **and** clear the halt (`DELETE /v1/ledger/traces/{trace_id}/halt`, scope
   `admin`, or `ControlPlaneClient.clear_halt`). Clearing the flag alone re-trips immediately
   because the accumulator is still over the unchanged limit.
2. **Continue on a new trace.** Start a new run (a new Chronicle trace) with a clean budget and
   rebuild the agent's context from the halted trace's recorded envelopes. The halted trace
   stays an immutable record.
3. **Prove a fix by replay.** Replay the halted span with Chronicle, with the original cap (it
   halts) and with the raised cap (it passes):
   `chronicle.replay_trace(trace_id, span_id, ReplayPlan().stub("tool").run("agent.chat"))`.
   A replay is bounded by what was recorded. See `tests/e2e`.

## Multi-process runs

The halt is read through `precheck` and written with a synchronous `halt_mark`, so the second
process sees it on its next pre-call. Spend and completion events are written in the
background, so another process sees this process's spend after the queue delay
([ADR 0003](adr/0003-ledger-spend-writes-are-asynchronous.md)); a process always sees its own.
