# step_cap — opt-in step ceiling

Companion to the policies LLD and `halt.md`. Optional / opt-in (not a default).

Code: `tokenops-dev/src/tokenops/control/policies/step_cap.py`
Tests: `tokenops-dev/tests/test_step_cap.py`

---

## TL;DR

A cheap circuit breaker on **number of boundary crossings** per run. Trips at **observe**
when the run's step count reaches the cap, and the action it takes is **HALT**. It does not
depend on pricing — useful when a workflow has a known, bounded trajectory.

## Detect (formula)

```
steps(run) ≥ max_steps        # per recorded event; per run, not per period
```
Read from `step.step` (the monotonic per-run count, == `view.step_count` at that moment).
In A2A the shared run sums both agents' steps, because both record into the same run.

## Action it takes to govern — HALT

Identical mechanism to `cost_budget` (see `halt.md`): `Signal(TRIP)` → `Action(HALT)` →
flag set before raise → sticky kill switch. The difference is purely the *trigger* (step
count, not spend).

## Why opt-in, not default

Step count is **task-dependent** — a legitimate research run may take 5 or 50 steps, so a
fixed cap risks cutting off real work. Budget is the universal backstop; `step_cap` is for
workflows whose trajectory length you actually know and want to bound.

## Edge cases

* Trips at **exactly** `max_steps` (the cap-th recorded crossing), allows at `max_steps − 1`.
* Counts **every** crossing — llm, tool, and delegate alike — because each is one recorded
  step.

## I/O & success criteria (test contract)

| Input | Expect |
|---|---|
| `step = max_steps` | `Signal(TRIP)` → `Action(HALT)` |
| `step = max_steps − 1` | `None` (ALLOW) |
| e2e: 3 tool crossings, `max_steps = 3` | halts on the 3rd; `step_count == 3` |

## Status

✅ implemented, ✅ tested (unit + e2e). Uses tool crossings in e2e to isolate step counting
from budget.
