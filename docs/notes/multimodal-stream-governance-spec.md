# Spec: multimodal stream governance

Status: draft / design
Scope: cost governance of continuous media streams (audio, video, realtime
voice). Provider-agnostic. Safety and content moderation are explicitly out of
scope; this governs spend, not what the stream contains.

## Problem

TokenOps today governs **discrete, post-hoc** work. A model call happens,
returns, is priced (`input_tokens x price + output_tokens x price`), the ledger
updates, and the next call is checked before it dispatches. Every part of that
assumes a call is atomic and short.

Continuous streams break all three assumptions:

1. **No discrete boundary.** A voice or video stream has no single return to
   price. Cost accrues while frames flow.
2. **Cost is a rate, not a sum.** The runaway failure mode is not "many cheap
   calls added up," it is "a stream that should last ten seconds lasted ten
   minutes," or "frames arriving faster or larger than budgeted." We govern
   duration and throughput.
3. **Pre-call checking is too coarse.** There is no "before the call" when the
   call is the whole stream. Governance must happen mid-stream, and at near-zero
   overhead: a millisecond-scale check between millisecond-scale frames must not
   break real time.

This spec extends the discrete governor to a continuous one without a new
enforcement engine, by reusing primitives that already exist.

## What we build on (already present)

- **`Governor.tick(now)`** is a time-based moment, not call-based. It already
  exists and is the natural hook for stream governance.
- **`stream_complete`** exists in `providers/factory.py`.
- **`ActionKind.CANCEL`** is already declared (tracked in issue #67, currently
  unimplemented). Its purpose is exactly this: stop a stream mid-flight, keep the
  partial output, bill only what was consumed. This spec is what gives CANCEL a
  reason to exist.
- **The ledger** already accumulates spend keyed by
  `(budget_id, segment_key, period)` and supports `HALT` per run. Stream spend is
  more spend against the same accumulators; no new ledger shape is required.

## Design

### Unit of accounting: time-windowed accrual

We do **not** price per frame. Each open stream accrues cost locally as frames
arrive, and the accrued delta is flushed to the ledger on a fixed **accrual
window** (default 500 ms). Budget checks run at flush time, not per frame.

This bounds governance overhead independent of frame rate, and it matches how the
failure manifests (duration and rate, not individual frames). A 90-frames-per-
second video stream and a 16-kHz audio stream both cost the same governance:
two ledger touches per second.

### Stream lifecycle and the governance seam

A governed stream is wrapped the way a call is, but the wrapper sits in the
iteration loop rather than around a return:

```
open  -> admit (inflight++), start accrual clock
frame -> accrue local cost (no ledger, no check)
window-> flush accrued delta to ledger; run stream detectors; maybe act
close -> flush final delta, complete (inflight--)
```

Proposed entry point, mirroring `wrap_complete`:

```python
governed_stream = wrap_stream(
    governor, controls, attr,
    provider=..., model=..., modality="audio",
    dispatch=stream_complete,
    accrual_window_s=0.5,
)
for chunk in governed_stream(...):
    ...   # CANCEL is raised from inside the loop, tearing the stream down
```

`wrap_stream` drives `Governor.tick(now)` on each accrual window. Detectors that
care about streams read the accrued state; detectors that do not are unaffected.

### Pricing: per-modality rate functions

Extend the existing `PriceFn` with rate-based pricing. Cost stays micro-USD
(`Micros`, int) end to end, as it is today.

How real providers bill a stream, as of 2026, tells us the abstraction we need.
Two shapes cover the field:

- **Token-metered.** OpenAI's Realtime API bills audio per token (roughly $32
  per 1M audio input tokens, $64 per 1M output, with cached audio about 80x
  cheaper). Gemini's Live API tokenizes audio at a fixed rate (about 32 tokens
  per second of input audio, 25 per second of output) and then prices those
  tokens. Either the provider reports token counts on its stream events, or a
  fixed tokens-per-second constant derives them from elapsed time.
- **Time-metered.** Gemini prices video at a flat rate per second (about $0.15/s);
  some speech models bill per minute. Here the billable quantity is simply
  elapsed stream time.

The unifying observation: **the universal underlying unit is seconds of stream**,
which each provider maps to its billable quantity, directly (time-metered) or via
a fixed tokens-per-second conversion (token-metered). Direction (input vs output)
and a cache-hit flag both change the rate, mirroring how existing text pricing
already handles input/output and cached tokens.

So the price function signature generalizes to:

```
price(modality, direction, quantity, cached) -> Micros
```

A provider **stream adapter** maps that provider's stream events to a series of
`(modality, direction, quantity, cached)` records per accrual window; the price
function turns them into `Micros`. Rates are provider-supplied config, never
hardcoded. The governor never sees provider specifics, which is what keeps this
provider-agnostic.

### The three voice pipelines, concretely

Voice is the first real target, and it is three distinct pipelines. They bill in
three different units, yet the accrual model above covers all three unchanged.
Approximate 2026 prices are given as anchors, not as configuration.

| Pipeline | Flows | Billed by | Runaway risk | Anchor price |
|---|---|---|---|---|
| Speech-to-speech | audio in and out | audio tokens, both directions (output ~2x input) | a conversation that never ends | Realtime API, ~$64 / 1M audio output tokens |
| Speech-to-text | audio in, text out | minutes of audio in (or audio-in tokens) | an hour-long audio file | Whisper, ~$0.017 / minute |
| Text-to-speech | text in, audio out | characters, or text-in + audio-out tokens | unbounded text to speak | OpenAI TTS, ~$15 / 1M characters |

The point of the abstraction: three billing units (tokens, minutes, characters)
and two directions collapse into one `price(modality, direction, quantity,
cached)` call and one accrual loop. Speech-to-speech is the hardest case because
it is bidirectional and continuous, so it is the natural first implementation
target; the accrual clock meters input and output as separate directions on the
same window.

Each pipeline has a distinct denial-of-wallet shape, which is why the detectors
below cover duration, spend, and rate rather than any single one: a
speech-to-speech session runs away on *duration*, a transcription job on input
*size*, and a synthesis job on output *volume*.

### Detectors (new, stream-scoped)

Three, matching the real failure modes, smallest first:

1. **`stream_duration_cap`** trips when a single stream exceeds a wall-clock
   ceiling. Cheapest, no pricing dependency, the natural sibling of `step_cap`.
   Moment: `tick`. Action: `CANCEL`.
2. **`stream_spend_cap`** trips when accrued stream cost (this stream, or the
   run total including streams) crosses budget. Moment: `tick`. Action: `CANCEL`,
   then `HALT` if the run as a whole is over.
3. **`stream_rate_guard`** trips when throughput (bytes/sec, frames/sec, or
   resolution) exceeds an expected envelope, catching a stream that is quietly
   more expensive than budgeted. Moment: `tick`. Action: `MUTATE` (e.g. request a
   lower bitrate or resolution), then `CANCEL`.

### Actuator: CANCEL (closes issue #67)

CANCEL is the streaming actuator. On CANCEL:

1. The wrapper stops iterating and tears down the provider stream cleanly (no
   leaked socket or generator).
2. The final accrued delta is flushed, so the ledger reflects exactly what was
   consumed, not the full intended stream and not zero.
3. The partial result gathered so far is returned to the caller.

Billing correctness at teardown (charge for consumed frames only) is the
substance of the implementation, and the reason CANCEL is distinct from HALT.
HALT stops the run; CANCEL stops one stream and lets the run continue.

## Security notes (in scope, ties to the threat model)

Streaming widens the attack surface in ways worth stating:

- **Frame ingress is untrusted-input-facing.** A provider adapter parses
  provider frames; a malformed or hostile frame stream must not crash or stall
  the governor. This path should be fuzzed.
- **Denial of wallet is the primary risk.** An unmetered or under-metered stream
  is exactly the failure this feature exists to prevent; the accrual clock must
  be monotonic and must keep flushing even if frames stall, so a stalled-open
  stream still trips `stream_duration_cap`.
- **The accrual window is a security parameter, not just performance.** Too large
  a window means a runaway can spend a full window before the first check. The
  default must be small enough that worst-case unmetered spend is bounded and
  documented.

## Out of scope (v1)

- Content safety / moderation of stream contents.
- Cross-process stream aggregation (a stream split across hosts). Single-process
  accrual first; the shared ledger already handles cross-process spend totals if
  needed later.
- Video pricing beyond a simple per-frame or per-megapixel rate.

## Phasing

1. `wrap_stream` + accrual clock + `tick`-driven flush, single modality (audio).
2. CANCEL implementation and billing-at-teardown (issue #67).
3. `stream_duration_cap`, then `stream_spend_cap`, then `stream_rate_guard`.
4. Video modality and resolution-scaled pricing.

Each phase is independently shippable and testable offline with a scripted
frame source, no provider account required, matching how the existing policy
tests run.
