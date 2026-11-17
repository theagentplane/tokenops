# Budget pace

*Tell the model how much of a soft budget it has used, and how fast.*

**Policy ID:** [`budget_pace`](../product/policies-index.md)

Opt-in. Never halts.

Code: [`src/tokenops/framework/policies/budget_pace.py`](../../src/tokenops/framework/policies/budget_pace.py)
Tests: [`tests/test_budget_pace.py`](../../tests/test_budget_pace.py)

---

## TL;DR

After every model call the model is shown, on its next call, the run's spend as a percentage of a
soft limit, with the same figure after the two calls before it. The line says the limit is soft, so
the model changes its strategy to spend less only where it expects no loss in quality. It is a
pacing signal for the model to weigh. The hard stop stays with `cost_budget`.

## Detect (formula)

```
pct(call n) = round(100 × cum_spent_micros(n) / soft_limit_micros)     (llm steps only)
signal      = WARN with [pct(n), pct(n-1), ..., pct(n-points+1)]       (every llm step)
```

Tool steps add no point. The percentage can pass 100.

## Action — INJECT

One message on the next call, newest first:

```
BUDGET PACE: soft budget 50% used (t-1: 41%, t-2: 35%). This is a soft budget, not a hard limit.
Change your strategy to spend less only if you expect no loss in the quality of your result;
otherwise ignore it and do what gives the best result.
```

The first calls of a run show fewer points. Messages differ every call, so they are not deduplicated;
each is consumed by the next dispatch.

## Parameters

| Key | Default | Meaning |
|---|---|---|
| `soft_limit_micros` | required | The threshold, in micro-USD of the run's spend. Must be > 0 |
| `points` | `3` | How many calls to show: the current one and `points - 1` earlier. Must be ≥ 1 |

```yaml
budget_pace: { soft_limit_micros: 1_500_000, points: 3 }
```

## I/O & success criteria (test contract)

| Input | Expect |
|---|---|
| spend after 3 calls: 35%, 41%, 50% | `50% used (t-1: 41%, t-2: 35%)` |
| a tool step | no signal, no new point |
| spend above the limit | the percentage over 100, no halt |
| `soft_limit_micros` ≤ 0 or `points` < 1 | `ValueError` at build time |
