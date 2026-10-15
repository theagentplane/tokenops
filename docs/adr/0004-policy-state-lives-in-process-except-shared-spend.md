# 0004. Keep policy state in process; only spend, in-flight and halt are shared

| Field | Value |
|---|---|
| Status | Proposed |
| Date | 2026-10-15 |
| Deciders | Susheem Koul, Tisha Chawla |

## Context

TokenOps 0.4 stored a per-run step window and per-policy statistics in its own store and, in
remote mode, on the control plane. Control plane 1.0 stores neither (control-plane ADR 0009): it
keeps spend and in-flight counters and a halt, as ledger tables (ADR 0008) and a trace attribute
(ADR 0006). Issue 162 asks, per policy, whether the state it used is kept in process or derived
from traces, and what to do with per-policy statistics such as `context_compaction` savings.

What each policy reads (verified in `control/policies`):

- shared spend, via `precheck`: `cost_budget`, `pre_call_worst_case`, `cost_guard`;
- shared in-flight count, via `precheck`: `concurrency_cap`;
- the step window or step count of this process: `step_cap`, `progress_guard`,
  `context_compaction`, and the velocity part of `cost_guard`;
- only the current call: `output_runaway`, `tool_fix`, `tool_output_cap`;
- the wall clock: `time_budget`.

## Options considered

### Option A: derive the step window from traces on the plane

- Good: one view of a run across processes.
- Bad: a read of envelopes on the pre-call path, for policies whose state is a short recent tail;
  couples governors to the trace query API.

### Option B: keep the window in process

- Good: no read on the pre-call path; matches what the code did already (`LocalRunState`).
- Bad: a window is per process, so `step_cap` and `progress_guard` see only the steps this
  process took for the trace.

## Decision

We will keep policy state in process (Option B). Only spend, in-flight and halt are shared, and
they are read through `precheck`. The step window and step count are per process and per trace.
Per-policy statistics are not stored by the plane; `context_compaction` savings are recorded as
envelope metadata (`tokenops.compaction_*`) so they are visible in the trace.

## Consequences

- **Good:** nothing new on the pre-call path; no dependency on a trace query for governance.
- **Bad or risky:** in a multi-process run, `step_cap` limits each process's own steps, not the
  run's total. A shared step budget needs a plane counter, which the plane does not have.
- **Follow-ups:** `trajectory_hint` stays disabled; re-homing it needs a cross-run index, which
  is a separate decision. `time_budget` is not in the control plane's template allow-list, so a
  `time_budget` policy cannot be written to the plane yet (a control-plane issue).

## Impact on other repositories

control-plane: its template allow-list lacks `time_budget`.

## Links

- control-plane ADR 0006, 0008, 0009
- [ADR 0003](0003-ledger-spend-writes-are-asynchronous.md)
- Issue 162, section 4
