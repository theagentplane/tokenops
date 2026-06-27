# OUT controls — the seven actions the control plane can take

Companion to the policies LLD and `halt.md`. The OUT connector exposes one polymorphic
`apply(action)`; this is what each `ActionKind` means and which policies emit it.

Code: `tokenops-dev/src/tokenops/control/core.py` (`ActionKind`, `Action`),
`tokenops-dev/src/tokenops/control/engine.py` (`RaiseControls`).

---

## The two axes

Every control is either **preventive** (stop) or **corrective** (fix forward), and either
touches **control flow**, the **request envelope**, or the **conversation content**.

| Control | Kind | Touches | One-line |
|---------|------|---------|----------|
| **HALT** | preventive | control flow | stop the run, set the sticky flag (see `halt.md`) |
| **CANCEL** | preventive | control flow | hard-break a degenerate stream mid-flight |
| **REJECT** | preventive | admission | 429 backpressure — caller's backoff resubmits |
| **QUEUE** | preventive | admission | bounded-semaphore backpressure (single process) |
| **MUTATE** | corrective | request envelope | rewrite the outgoing call before dispatch |
| **INJECT** | corrective | conversation content | add a message / replace a tool result fed to the next turn |
| **RETRY** | corrective | request envelope | re-issue with new params (penalties, tighter cap) |

`ALLOW` is the no-op (a fired signal the policy chose not to act on).

## MUTATE vs INJECT — the subtle pair

Both "fix forward" without stopping the run. The line:

* **MUTATE** changes **how the call is configured** — which model, the output cap, the
  assembled prompt. Editing the letter before you mail it.
* **INJECT** changes **what content is in the conversation** — a synthetic tool result, an
  error message, an instruction. Slipping a note into the mailbox.

### Who emits MUTATE, and what they mutate

| Policy | Mutates | `Action` payload |
|--------|---------|------------------|
| `pre_call_worst_case` | the **output cap** | `max_output_tokens` |
| `cost_guard` (`mode="downgrade"`) | the **model** | `downgrade_to` |
| `context_compaction` (`has_hook=True`) | the **prompt** | compaction directive |

This is exactly the LLD's MUTATE = *"swap model, cap output, rewrite prompt."*

### Who emits INJECT, and what they inject

| Policy | Injects |
|--------|---------|
| `tool_fix` | a synthetic tool result `{error, did_you_mean, available_tools}` |
| `tool_output_cap` | a descriptor `{size, count, handle}` replacing an oversized payload |
| `progress_guard` | a deterministic "no progress, change approach" correction |
| `cost_guard` (`mode="minimize"`, default) | a "keep output minimal" instruction |
| `output_runaway` (after retries) | a "generation degenerated" error |

## Who emits the preventive controls

| Control | Policies |
|---------|----------|
| **HALT** | `cost_budget`, `step_cap`, `pre_call_worst_case` (worst case), `tool_fix` (after K), `progress_guard` (after K) |
| **CANCEL** | `output_runaway` (stream path) |
| **REJECT / QUEUE** | `concurrency_cap` |
| **RETRY** | `output_runaway` (bounded, before INJECT) |

The breaker owns HALT and CANCEL; every other policy heals or bounds.

## Apply requirements + status (what makes each actually work)

`RaiseControls` (brownfield) does **HALT** only. The greenfield `ApplyControls` behind the
provider wrap (`wrap_complete` / `wrap_stream`) applies the rest. All seven are now built:

| Control | Applied by | Status |
|---------|-----------|--------|
| HALT | `RaiseControls` / `ApplyControls` raise `Halt` | ✅ live |
| MUTATE (model / output cap) | `wrap_complete` reads `controls.call` | ✅ live |
| MUTATE (deep prompt compaction) | `Action.compact` → `wrap` rewrites outgoing messages (dedup, pin system) | ✅ live |
| INJECT (next-call message) | `controls.carry` prepended | ✅ live |
| INJECT (deep tool-result swap) | `Action.replace_tool_result` → agent `take_tool_result()` substitutes the result | ✅ live (research-native; `tool_output_cap`) |
| RETRY | bounded loop in `wrap_complete`: re-issue with tighter cap + raised penalties | ✅ live |
| REJECT / QUEUE | `Throttled` → 429 + Retry-After at the boundary | ✅ live |
| CANCEL | `wrap_stream` + `providers.stream_chat`: detect degeneration, `generator.close()` mid-flight | ✅ built + tested; **not in the default live path** (agent calls the non-streaming wrap — switch it to `wrap_stream` to activate) |

Under `RaiseControls`, any unsupported corrective kind still **fails closed to HALT**.

## Remaining parity work

- **CANCEL** is implemented and tested but the native agent runs non-streaming, so it only
  fires when the server uses `wrap_stream`. Flip the model call to streaming to activate.
- **`tool_fix`** INJECT still uses the carry (next-message) path; only `tool_output_cap`
  does in-place tool-result substitution.
- Deep hooks are wired into **research-native** only — not the summarize or LangChain variants.
