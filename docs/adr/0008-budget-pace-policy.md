# 0008. Show the model its soft-budget usage and trend, in a new opt-in policy

| Field | Value |
|---|---|
| Status | Proposed |
| Date | 2026-11-17 |
| Deciders | Susheem Koul |

## Context

The policies that act on spend either stop the run (`cost_budget`, `step_cap`) or steer only once a
limit is near (`cost_guard`, `progress_guard`'s "change approach or finalize"). None gives the model
a running view of how much it has used and how fast, so it cannot pace itself before a limit is
close. We want to try showing that, as advice the model weighs against quality, on Terminal Bench
and SWE-bench runs.

## Options considered

### Option A: a new opt-in policy, `budget_pace`

- Good: a detector emits one signal per step and `progress_guard` already uses its slot for stalls and
  keeps a correction counter that escalates to HALT; a separate policy leaves both untouched.
  Can be switched on and off for a comparison with one config key.
- Bad: one more template to document and, if the control plane validates policy keys, to allow-list.

### Option B: a parameter on `progress_guard`

- Good: no new template.
- Bad: mixes a pacing hint into a stall detector, and its single signal per step would have to
  choose between the two or merge them.

## Decision

We will add Option A. After each model call `budget_pace` computes the run's cumulative spend as a
percentage of `soft_limit_micros` and INJECTs it with the earlier `points - 1` calls (default 3)
on the next call. The text says the limit is soft and that the model should change strategy only if it
expects no loss in quality. It never trips or halts; `cost_budget` stays the hard limit.

## Consequences

- **Good:** an opt-in way to measure whether pacing information alone lowers cost without
  lowering the pass rate; no change to any existing policy.
- **Bad or risky:** the model may economise when it should not (the text asks it not to, and nothing
  enforces that), and a line is added to every call's prompt (about 60 tokens). Spend is the only
  measure; tokens or steps are not offered. A new message each call is not deduplicated by the carry.
- **Follow-ups:** a token or step threshold if cost proves the wrong unit; a benchmark run that compares
  it with and without.

## Impact on other repositories

control-plane: the `budget_pace` template and its parameters (`soft_limit_micros`, `points`) must be
allowed, if it validates policy keys. tokenops-benchmarking: a config that enables it, after a release.

## Links

- [budget_pace policy](../policies/budget_pace.md)
