# HALT — semantics, mid-flight behaviour, and resume

Companion to the policies LLD. Covers what HALT actually *does* to a running agent,
why it does not interrupt an in-flight call, and exactly how someone resumes the work.

Code: `tokenops-dev/src/tokenops/control/engine.py` (Governor, RaiseControls),
`tokenops-dev/src/tokenops/control/ledger.py` (halted flag, window),
`tokenops-dev/src/tokenops/control/policies/cost_budget.py` (the canonical HALT producer).

---

## TL;DR

* HALT stops a run **between boundaries**, never in the middle of a model request.
* The call that breached the budget has **already returned and been counted** — its
  output lives in the window. We don't abort it (no tokens would be saved).
* HALT **unwinds** the agent loop (raises `Halt`), it does **not** suspend it.
* Therefore **resume = restart with state reconstructed from the ledger window**, not
  "continue the exact call stack". A true suspend/continue is `PAUSE` (future, needs a
  checkpointable runtime).
* The **flag is set before the raise**, so HALT is sticky: every later call is refused
  even if the agent swallowed the exception.

---

## 1. What HALT is — and is not

| | |
|---|---|
| **Is** | A preventive, sticky, idempotent stop applied at a boundary crossing. |
| **Is not** | An interrupt of an in-flight HTTP request to the model. That is `CANCEL`. |

HALT answers "should this run make its **next** call?" with "no, and never again until
explicitly resumed." It does not reach into a socket and tear down a request that is
already streaming tokens.

## 2. The three points HALT can fire

All three are boundaries — the gaps *between* units of work, not inside one.

| Point | When | What is already spent | Code |
|-------|------|-----------------------|------|
| **pre_call** | before a call dispatches | nothing (call never starts) | `Governor.pre_call` → detector `pre_call` |
| **observe** | after a crossing is recorded | the just-finished call (already counted) | `Governor.observe` → detector `observe` |
| **kill switch** | before any moment, run already halted | n/a — refused at the IN edge | `Governor._refuse_if_halted` |

`cost_budget` (the guarantee) fires at **observe**: it trips the moment an accumulator
crosses its limit, which is *after* the breaching call returned. `pre_call_worst_case`
(the prevention) fires at **pre_call**, so the over-budget call never starts.

## 3. Why we do not abort the in-flight call

When `observe` trips, the model call that pushed spend over the limit has **already**:
1. been sent, 2. consumed input + output tokens, 3. returned, 4. been priced and added
to `spent` (that is *why* the accumulator crossed the limit), 5. been appended to the
window with its `usage`, `output`, and `cum_spent_micros`.

Killing that request mid-flight would save **zero** tokens — they are already billed —
and would throw away a completed, useful result. So we keep the result (it is in the
window) and simply refuse the *next* call. This is the same rule `concurrency_cap`
follows: never kill admitted work.

The only control that *does* hard-break an in-flight operation is **CANCEL**, used by
`output_runaway` to stop a degenerate **stream** that is actively bleeding tokens — there,
stopping mid-flight genuinely saves tokens, so the trade-off flips.

## 4. HALT vs CANCEL vs PAUSE

| Control | Stops | Mid-flight? | Resumable? |
|---------|-------|-------------|-----------|
| **HALT** | the whole run | no — between boundaries | only by explicit re-grant or continuation |
| **CANCEL** | one stream | yes — tears down the stream | the run continues (heal/retry), the stream is gone |
| **PAUSE** | the run, suspended | no | yes — continue the suspended runtime (future, checkpointable only) |

## 5. What state survives a HALT

`Halt` is a `BaseException` raised through the agent's existing callback. It unwinds the
agent's call stack. So:

**Survives (it lives in the Ledger, not the agent stack):**
* `runs[run_id].halted` + `halt_reason` — the durable kill switch.
* `runs[run_id].window` — the **full, append-only trajectory**: every BoundaryStep with
  its `input`, `output`, `usage`, `signature`, `result_hash`, and `cum_spent_micros`.
* `spent[...]` accumulators and the run total (`cost_micros`).

**Lost (it lived on the agent's local stack):**
* The agent's in-memory working state — e.g. `NativeResearchAgent.run`'s local
  `findings` / `context` lists. When `Halt` unwinds past `return findings`, those locals
  are gone **unless** they were checkpointed.

> **Honest gap (current implementation):** we preserve the *ledger* trajectory, but we do
> not yet capture the agent's partial *work product* at the halt boundary. Two ways to
> close it (see §7): reconstruct findings from the window, or have the boundary catch
> `Halt` and return the partial result it was accumulating. Neither is wired yet.

## 6. How to resume — three mechanisms

HALT is terminal **by design**; resume is always a deliberate, audited act. Pick one:

### (a) Re-grant — same `run_id`
For "this run hit its cap but is authorized for more."
1. An authorized actor raises the breached limit (or the relevant accumulator gains
   headroom).
2. `ledger.clear_halt(run_id)` lifts the gate.
3. Re-invoke the agent loop **seeded** from the window (§7) — the same `run_id`, window
   intact, spend continues from where it stopped.

> Note from the smoke test: `clear_halt` **alone** re-trips immediately, because the
> accumulator is still over the (unchanged) limit. Re-grant means *clear the flag AND
> raise the cap* — one without the other is a no-op resume.

### (b) Continuation — new `run_id`, `parent_run = halted run`
The common, safe "carry on" — the halted run stays a frozen, immutable record.
1. `open_run(new_run_id, parent_run=halted_run_id)` — clean budget, lineage preserved.
2. Seed the new run's agent context from the halted run's window (§7).
3. Run forward. Cost lineage rolls up to the parent via `parent_run`.

This is *why the window is append-only and unbounded*: it is the durable memory a
continuation rebuilds from.

### (c) PAUSE instead of HALT — future
If the stop is a *corrective* "needs a human", not the budget *guarantee*, the right
control is `PAUSE`: suspend + checkpoint + await approval, then continue the suspended
runtime. Resumable by construction. Requires a checkpointable agent runtime (greenfield),
which the brownfield raise-based model does not provide.

## 7. Reconstructing state to carry on

Because brownfield HALT unwinds (does not suspend), resume = **re-invoke the agent with
its context rebuilt**. The window is the source:

```python
# Rebuild research findings from the halted run's trajectory.
findings = []
for step in ledger.window(halted_run_id):
    if step.node_type == "tool" and step.boundary_id == "search":
        findings.append(step.output)        # snippet, completeness, … were stored here
seed_context = findings                      # hand to agent.run(task, seed=seed_context)
```

The window already holds each tool result (`step.output`) and each llm decision
(`step.output.text` / `tool_calls`), so the trajectory is fully replayable for seeding.
A richer alternative is an explicit work-product checkpoint the agent writes as it goes
(so resume does not re-derive from raw steps) — an optimisation, not a requirement.

## 8. A2A note

In single process, `runs[run_id].halted` is the kill switch. In distributed A2A the same
field is backed by the shared store, so **every** agent's IN connector refuses further
calls on a halted run. Roll child cost into the parent *before* setting the flag, so the
halted run's total reflects the whole run. The flag set is idempotent.

## 9. Implementation status (honest)

| Capability | Status |
|---|---|
| HALT at `observe` (post-record), sticky flag, kill switch | ✅ done + smoke-tested |
| HALT at `pre_call` | ✅ harness supports it; needs the provider wrap (Phase 5) to fire in the real agent |
| `clear_halt` (re-grant gate lift) | ✅ done |
| Window preserves full trajectory | ✅ done |
| Reconstruct agent context from window (§7) | ⛔ designed, not wired |
| Capture partial work product at the halt boundary | ⛔ designed, not wired |
| Continuation run seeding / re-grant cap-raise flow | ⛔ designed, not wired |
| A2A shared-store backing of `halted` | ⛔ single-process only for now |
| CANCEL (stream abort) / PAUSE (suspend) | ⛔ not built (output_runaway / greenfield) |
