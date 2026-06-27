# Customer outcomes

What end users care about: **cheaper runs, more tasks finished under budget, without worse output.**

Policy fire rates, halt counts, and latency are useful for tuning TokenOps — but they are second-order metrics. The first-order proof of value is whether governed agents deliver more useful work per dollar.

See also: [why-token-governance.md](./why-token-governance.md) (problem framing), [Dashboard](../src/tokenops/ui/pages/2_Dashboard.py) (run history today).

---

## The three outcomes

| Outcome | Question |
|---|---|
| **Cheaper** | Did average cost per run go down? |
| **More done** | Did more runs finish inside the budget cap? |
| **Still good** | Did output quality hold? |

All three must move together. Lower cost with worse answers is not a win. More completions by cutting corners is not a win.

---

## 1. Average cost reduced

**Metric:** Mean and median **cost per run** — all runs, then completed runs only.

Compare TokenOps against two baselines:

| Baseline | What it represents |
|---|---|
| **Ungoverned** | Same tasks, no governance — runaway spend possible |
| **Simple throttle** | Hard stop at budget cap — no steer, inject, or compaction |

Report **median** as well as mean so one runaway run does not define the story.

**User story:** *"We cut average run cost by X% on the same task mix."*

---

## 2. More runs completed within budget

**Metric:** **Completion rate under budget**

```
completed_within_budget / runs_started
```

Where:

- **Completed** — run finished with a valid result (not halted mid-task)
- **Within budget** — final spend ≤ cap (`RunRecord.cost_micros` vs budget limit)

**Delta vs simple throttle:**

```
(completion_rate_tokenops − completion_rate_throttle) / completion_rate_throttle
```

Simple throttling caps spend but often leaves tasks incomplete. TokenOps steers the run (`cost_guard`, `context_compaction`, `progress_guard`) so more jobs **finish** before hitting the cap.

**User story:** *"Y% more jobs finish under the $2 cap than with a hard cutoff."*

---

## 3. Output quality unchanged

This is the guardrail. Without it, "cheaper + more completions" may mean worse answers.

Pick **one or two quality signals per intent** — not ten:

| Intent type | Practical quality proxy |
|---|---|
| Research / summarize | Rubric score, citation coverage, sampled human review |
| Support / triage | Resolution rate, escalation rate, CSAT |
| Code / tool agents | Task pass rate, test success, tool error rate |

Require quality ≥ baseline (within an agreed tolerance) before claiming a cost or completion win.

**Optional composite:** quality-adjusted efficiency

```
(completion_rate_within_budget × quality_score) / avg_cost
```

**User story:** *"Same quality score (±ε), 30% lower cost, 20% more jobs finished under cap."*

---

## One-slide summary

```
Before (ungoverned)   →  high cost, unpredictable, some runaway
Throttle only         →  cost capped, many incomplete runs
TokenOps              →  lower avg cost, more completions, quality ≥ baseline
```

Three numbers:

1. **Avg cost per completed run** ↓
2. **% runs completed within budget** ↑ (vs throttle)
3. **Quality score** ≈ (within tolerance)

---

## What to record per run

Minimal fields for these three outcomes (extend `RunRecord` / export pipeline):

| Field | Purpose |
|---|---|
| `final_cost`, `budget_limit`, `status` | Cost and completion under cap |
| `baseline_profile` | `ungoverned` / `throttle_only` / `tokenops` |
| `quality_score` | Intent-specific, computed post-run |
| `intent`, user tags | Segment results by workflow and customer |

**Shadow throttle** — run throttle-only logic in parallel without enforcing — gives completion and cost deltas from the same traffic without a full A/B test. The simulator and control-plane trace are starting points for replay-based baselines.

---

## First-order vs second-order metrics

| First-order (customer value) | Second-order (tuning TokenOps) |
|---|---|
| Cost per completed run | Halt rate by policy / `detector` |
| Completion rate under budget | INJECT / MUTATE / HALT mix |
| Quality score | Budget utilization histogram |
| Delta vs throttle baseline | `pre_call` / `observe` latency |
| Overrun prevention ($) | Rescue-after-inject rate |

Lead with first-order metrics in customer conversations and case studies. Use second-order metrics internally to improve policy defaults and operator tooling.

---

## Implementation notes (product repo)

Today the dashboard exposes `cost_micros`, `steps`, `status`, and `halt_reason` per run. To support customer-outcome reporting:

1. Persist `budget_limit` and `baseline_profile` on run close
2. Add post-run `quality_score` hook (intent-specific evaluator)
3. Shadow `throttle_only` governor on same ledger window for delta metrics
4. Aggregate by `intent` and registration tags in dashboard export
