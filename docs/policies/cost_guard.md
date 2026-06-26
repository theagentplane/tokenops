# cost_guard — POC: instruction-based minimization

Companion to the policies LLD, `halt.md`, and `controls.md`.

Code: `tokenops-dev/src/tokenops/control/policies/cost_guard.py`
Tests: `tokenops-dev/tests/test_cost_guard.py`

---

## TL;DR

As a run approaches its budget, nudge it cheaper *without* a hard cap. At **observe**, when
spend crosses 0.8 of the limit (edge-triggered, once), the action is **INJECT** a "keep
output minimal" instruction — or, in routing mode, **MUTATE** the next call to a cheaper
model. A hard output cap is deliberately avoided (partial output → re-call → more cost).

## Detect (formula)

```
spent(seg)/limit ≥ 0.8     (edge-triggered)     OR     velocity over last M ≥ threshold
```
`spent = limit − budget_left`. **Edge-triggered** means it fires **once** when crossing the
threshold (tracked per run), not on every later step — otherwise it would re-inject the same
instruction repeatedly and its own auxiliary cost would pile up.

## Action it takes to govern — INJECT (default) or MUTATE (routing)

| Mode | Action | What it does |
|---|---|---|
| `minimize` (default) | **INJECT** | "keep responses minimal; omit preamble/restatement" |
| `downgrade` | **MUTATE** (`downgrade_to`) | swap the next call to a cheaper model (do an elasticity check first) |

It never HALTs — it is a steer, not a stop. The guarantee (`cost_budget`) is the backstop if
the steer isn't enough.

## Why a POC, not a default-on hard cap

The instruction itself costs tokens, so it only pays off if the savings exceed that
auxiliary cost — hence "POC to confirm savings." And a hard `max_output` cap risks truncating
a useful answer, forcing a re-call that costs *more*. Minimization-by-instruction avoids that
failure mode.

## I/O & success criteria (test contract)

| Input (FakeView) | Expect |
|---|---|
| `budget_left=20_000` of 100_000 (ratio 0.8) | `WARN` once; second call `None` (edge) |
| `budget_left=30_000` (ratio 0.7) | `None` |
| mode minimize | `INJECT` "…minimal…" |
| mode downgrade, `downgrade_to=…` | `MUTATE(downgrade_to)` |

## Status

✅ implemented, ✅ tested (unit). Velocity trigger and elasticity check are wired as config
options; INJECT/MUTATE application lands with the provider wrap (Phase 5).
