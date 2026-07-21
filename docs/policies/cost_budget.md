# cost_budget — the guarantee

Companion to `halt.md`. Documents the governance action this policy
takes. Default, always-on.

Code: `tokenops-dev/src/tokenops/control/policies/cost_budget.py`
Tests: `tokenops-dev/tests/test_cost_budget.py`

---

## TL;DR

The universal spend backstop. Trips at **observe** the moment a budget accumulator crosses
its limit, and the action it takes is **HALT** — sticky, idempotent, run-wide. It does not
prevent the breach (that is `pre_call_worst_case`); it *guarantees* you cannot stay over.

## Detect (formula)

```
∃ budget B: spent(seg_B) ≥ limit_B
```
Implemented as `budget_left(budget_id, segment_key, period) ≤ 0`, read off the same
accumulator the ledger writes — detection and accounting can never disagree (single source
of truth). The detector ignores events whose `segment_key` is `None` (the budget's
dimension is absent on this event).

## Action it takes to govern — HALT

1. Detector emits `Signal(TRIP)` with evidence `{budget_id, segment, left_micros}`.
2. Policy maps any TRIP → `Action(HALT)`.
3. Governor sets `runs[run_id].halted` **before** applying (so the flag survives a
   swallowed raise), then the OUT connector raises `Halt`.
4. The agent loop unwinds; every later call is refused at the IN edge (kill switch).

Child cost was already rolled into the parent at `record` time, so the halted run's total
reflects the whole run. See `halt.md` for mid-flight behaviour and resume.

## Edge cases

* The **breaching call is kept** — it already returned and is in the window; we refuse the
  *next* call, not the one that tipped over (no tokens saved by aborting it).
* **Unlimited budgets** (`limit_micros = None`, e.g. the system run-total) return
  `UNLIMITED_LEFT` and never trip — they accumulate for measurement only.
* HALT is **idempotent**: marking an already-halted run twice is harmless.

## I/O & success criteria (test contract)

| Input (FakeView) | Expect |
|---|---|
| `budget_left = 0` | `Signal(TRIP)` → `Action(HALT)` |
| `budget_left = 1` | `None` (ALLOW) |
| e2e: 3 llm calls @9550 vs 20000 cap | halts on call 3; flag set; call 4 refused ("already halted") |

## Status

✅ implemented, ✅ tested (unit + e2e), ✅ sticky HALT + kill switch verified.
