# pre_call_worst_case — preventive ceiling

Companion to `halt.md`. Default (preventive).

Code: `tokenops-dev/src/tokenops/control/policies/pre_call_worst_case.py`
Tests: `tokenops-dev/tests/test_pre_call_worst_case.py`

---

## TL;DR

Stops a breach **before** spend. At **pre_call** it projects the call's worst case against
the remaining budget and takes one of two actions: **MUTATE** (bound the output cap so the
priced cap is the enforced cap) when the call fits but is uncapped, or **HALT** when even a
bounded worst case will not fit. Complements `cost_budget`: prevention here, guarantee there.

## What is `max_output`?

`max_output` (`max_output_tokens` on the `CallRequest`) is the **hard limit on how many
tokens the model is allowed to generate for this one response** — the provider parameter
you already pass today: OpenAI `max_tokens`, Anthropic `max_tokens`. It is the *output*
side of the call; `est_input` is the *input* side.

Why this policy cares about it:

* The cost of a call is `price(input) + price(output)`. You know the input (you're about
  to send it), but the **output is unknown until the model finishes**. To compute a
  *worst case* you must assume the model emits the most it's allowed to — i.e. exactly
  `max_output` tokens.
* If `max_output` is **unset**, the worst case is the model's *physical maximum* (e.g.
  4k–16k+ tokens) — a huge, usually meaningless ceiling that would make almost every call
  look like it breaches. The LLD rule is explicit: **never price the model's physical
  max.**
* So when a call arrives uncapped, this policy **sets** `max_output` to a sane default
  (`DEFAULT_MAX_OUTPUT`, 1024). That makes the number we *priced* in the worst case the
  number the provider will *actually enforce* — "priced cap == enforced cap." Without
  setting it, our projection would be a guess the provider isn't bound to.

In short: `max_output` is the lever that turns an unbounded "how expensive could this get?"
into a bounded, enforceable number we can safely gate on.

## Detect (formula)

```
spent(run) + price(est_in) + price(max(out, default)) ≥ budget
```
where `out` is the request's `max_output` and `default` is `DEFAULT_MAX_OUTPUT`.
Implemented against `budget_left` (segment-aware): `projected ≥ left`, where
`projected = price(Usage(input=est_in)) + price(Usage(output=capped_out))` and
`capped_out = max_output_tokens if set else DEFAULT_MAX_OUTPUT`.

## Action it takes to govern — MUTATE then HALT

Encoded as two severities so one `decide` returns one Action:

| Condition | Signal | Action |
|---|---|---|
| even with `capped_out`, `projected ≥ left` | `TRIP` | **HALT** — refuse before dispatch |
| fits, but `max_output_tokens` was unset | `WARN` | **MUTATE** `max_output_tokens = DEFAULT_MAX_OUTPUT` |
| fits and already capped | — | `None` (ALLOW) |

The MUTATE matters: we only trust a worst-case number if the cap we *priced* is the cap the
provider will actually *enforce*. Setting it closes that gap. MUTATE needs an OUT connector
that can rewrite the outgoing call (the provider wrap, Phase 5); `RaiseControls` cannot, so
under it MUTATE fails closed to HALT — by design.

## Edge cases / fail-closed

* **Unknown price** → `TRIP` (HALT). Never assume 0; never price the model's physical max.
* Uses `budget_left`, so an **unlimited** budget yields `UNLIMITED_LEFT` and never trips.
* `est_input` comes from the call request (prev input tokens or chars/4) — no tokenizing on
  the hot path.

## I/O & success criteria (test contract)

| Input | Expect |
|---|---|
| est_in 1000, no cap, left 1_000_000 | `WARN` → `MUTATE(max_output=1024)` |
| est_in 1000, cap 500, left 1_000_000 | `None` (ALLOW) |
| est_in 1000, no cap, left 20_000 | `TRIP` → `HALT` |
| unknown model | `TRIP` (`fail_closed=True`) |
| e2e: MUTATE recorded via CollectingControls; HALT raised after budget burned | both verified |

## Status

✅ implemented, ✅ tested (unit + e2e). MUTATE asserted through the Governor with a
collecting OUT connector; real provider-wrap application lands in Phase 5.
