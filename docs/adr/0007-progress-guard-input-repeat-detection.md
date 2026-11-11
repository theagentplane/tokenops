# 0007. Detect a stall from the unchanged input shown to the model, opt-in

| Field | Value |
|---|---|
| Status | Proposed |
| Date | 2026-11-11 |
| Deciders | Susheem Koul |

## Context

`progress_guard` detects a stall from what the agent did: the same tool `signature` with the same
`result_hash`, or a near-duplicate model output. A Terminal Bench 2.0 trial (Terminus 2,
`azure/gpt-5-mini`) left the terminal in a pager and varied its commands and its wording for 24
steps. The terminal showed the same screen 19 times, and neither check fired, because neither looks
at what the agent was shown. The model call's `messages` are already stored on each step. See
[issue 199](https://github.com/theagentplane/tokenops/issues/199).

## Options considered

### Option A: new opt-in detection on the newest message sent to the model

- Good: works for any agent that feeds results back as messages, with no tool boundary and no
  assumption about roles; the existing checks and defaults do not change.
- Bad: an agent that legitimately waits shows the same input repeatedly and gets nudged.

### Option B: match on the tool result alone, dropping the signature from the tool check

- Good: no new parameter.
- Bad: changes the meaning of a documented detection, and only works where tool results are reported.

## Decision

We will add Option A: `input_repeats` (default `0`, off) fires when the newest message of a model
call has the same text on at least that many calls in the window. Matching is exact after whitespace
collapse; `input_simhash_threshold` (default `0`, exact) switches it to SimHash near-duplicates. The
fix is unchanged: INJECT, then HALT after `max_corrections`. A message, not a halt, is the default
response because waiting is a legitimate cause.

## Consequences

- **Good:** a class of stalls that varies its actions becomes visible; the existing checks'
  detection, parameters and defaults are unchanged. The signal reason and the nudge text for the
  model-output check now describe what stalled (they used to say "same action with the same result").
- **Bad or risky:** false nudges for long silent waits; SimHash is weak on short messages; only the
  last message is compared, so a system reminder appended to it would defeat the exact match. Replays over recorded runs show where
  it would speak, not whether the nudge changes the outcome; a live run is still needed.
- **Follow-ups:** a fuzzy tool-result check.

## Impact on other repositories

control-plane: the `progress_guard` template parameters it allows (`input_repeats`,
`input_simhash_threshold`) must be accepted, if it validates them.

## Links

- [Issue 199](https://github.com/theagentplane/tokenops/issues/199)
- [progress_guard policy](../policies/progress_guard.md)
