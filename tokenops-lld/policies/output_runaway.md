# output_runaway — heals, never halts

Companion to the policies LLD, `halt.md`, and `controls.md`. Default.

Code: `tokenops-dev/src/tokenops/control/policies/output_runaway.py`
Tests: `tokenops-dev/tests/test_output_runaway.py`

---

## TL;DR

Catches a model that has fallen into a repetition loop in its visible output. The action is
to **CANCEL** the bleeding stream, **RETRY** a bounded number of times with stronger
anti-repetition settings, and if it is *still* degenerate, **INJECT** a "generation
degenerated" error and continue. It **never HALTs** — persistent failure is caught by the
backstops (`cost_budget` / `step_cap` / `progress_guard`).

## Detect (formula)

```
n-gram repetition over the streamed visible output: repeats ≥ R
OR single-token domination
OR tail-loop
```
Most runaways are *prevented* up front by setting frequency/presence penalties and a
`max_output` cap on the original request; this policy is the *recovery* when one slips
through. Detection is deterministic and model-free (`max_ngram_repeat`,
`single_token_domination`).

## Action it takes to govern — CANCEL → RETRY (bounded) → INJECT

| Step | Action | Detail |
|---|---|---|
| stream is degenerate | **CANCEL** | hard-break the stream to stop the token bleed (streaming wrap) |
| retry `< max_retries` | **RETRY** | raise frequency/presence penalties, tighten `max_output`, optional `logit_bias` on the looping tokens |
| retries exhausted | **INJECT** | "generation degenerated; proceed without this output" |

> Note: this observe-path detector runs on the **completed** visible text, so the stream has
> already finished — the policy goes straight to bounded RETRY then INJECT. In a true
> streaming wrap, CANCEL is the first action (stop mid-stream), which is where stopping
> actually saves tokens (unlike HALT — see `halt.md` §3).

## Why never HALT

A single degenerate generation is a transient quality problem, not a budget or safety
breach. Killing the whole run would throw away good prior work. The breaker backstops own
the hard stop if the degeneration also burns budget or steps.

## I/O & success criteria (test contract)

| Input | Expect |
|---|---|
| `output.text` with a 3-gram repeated 6× | `WARN` |
| clean unique text | `None` |
| degenerate ×4, `max_retries=2` | `RETRY, RETRY, INJECT`; **no HALT** |
| `node_type="tool"` | `None` (llm-only) |

## Status

✅ implemented, ✅ tested (unit). RETRY/INJECT detection + decisions done; CANCEL (true
stream tear-down) and the retry param application land with the streaming provider wrap
(Phase 5).
