# Time budget

*Opt-in wall-clock ceiling.*

**Policy ID:** [`time_budget`](../product/policies-index.md)

Code: [`src/tokenops/control/policies/time_budget.py`](../../src/tokenops/control/policies/time_budget.py)
Tests: [`tests/test_time_budget.py`](../../tests/test_time_budget.py)

---

## TL;DR

A cheap circuit breaker on **elapsed wall-clock time** per run. Trips at **observe**
when the run's age reaches the ceiling, and the action it takes is **HALT**. It does
not depend on pricing -- useful when a workflow's cost is latency rather than tokens.

## Detect (formula)

    elapsed(run) >= max_seconds

`elapsed` is `step.ts - start` where `start` is the timestamp of the first step
observed for that run (stored on the detector, O(1) per step).

## Action it takes to govern -- HALT

Identical mechanism to `cost_budget` and `step_cap`: `Signal(TRIP)` -> `Action(HALT)`
-> flag set before raise -> sticky kill switch. The difference is purely the trigger
(wall-clock age, not spend or step count).

## Why opt-in, not default

Elapsed time is task-dependent -- a legitimate research run may take 30 seconds or
30 minutes. Budget is the universal backstop; `time_budget` is for workflows whose
runtime you actually know and want to bound.

## Edge cases

* First step: elapsed is `0.0` (the ledger records the step before `observe` runs, so `step.ts - start == 0.0`).
* Trips at **exactly** `max_seconds` elapsed (>=).
* Counts wall-clock time across all node types -- llm, tool, and delegate alike.

## I/O & success criteria (test contract)

| Input | Expect |
|---|---|
| `elapsed >= max_seconds` | `Signal(TRIP)` -> `Action(HALT)` |
| `elapsed < max_seconds` | `None` (ALLOW) |
| e2e: two tool crossings, `max_seconds=0.5` | halts on the second |

## Status

Implemented and tested (unit + e2e).
