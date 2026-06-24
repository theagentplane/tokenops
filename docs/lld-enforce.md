# TokenOps Policies LLD

## Glossary 

| Term | Meaning |
|---|---|
| **segment** | a grouping a budget/policy attaches to: the value of one dimension (run, user, agent, tenant, or a tag). One event belongs to several segments at once. |
| **inflight(seg)** | how many calls for that segment have started but not yet returned **right now** (concurrent calls in progress). |
| **depth(run)** | how many delegation levels deep the run is. A → B → C = depth 3. Computed as parent.depth + 1. |
| **breadth(run)** | how many sub-agents this run has spawned directly. |
| **budget_left(run)** | remaining budget = `limit − spent`. |
| **window** | the last W events of the current run (a deque); used by loop, velocity, and progress checks. |
| **signature** | a stable hash of (tool name, args). |
| **result_hash** | a hash of the tool's result, to tell if a repeated call returned the same thing. |
| **SimHash** | a 64-bit fingerprint of a text; two texts are near-duplicates if their fingerprints' Hamming distance is small. Deterministic, no model. |
| **logit_bias** | a per-token bias added to the model's output scores before sampling, to make specific tokens more/less likely or ban them; used on a retry to stop the model repeating the tokens it was looping on. |
| **frequency / presence penalty** | decoding parameters that lower the probability of tokens already used (frequency) or already present (presence); set on the request to prevent or recover from degenerate, repeating output. |
| **est_input** | estimated input tokens for the next call (prev call's input tokens, or chars/4). Avoids tokenizing on the hot path. |
| **cum cost** | cumulative run cost stored on each window entry, so a velocity (slope) read is O(1). |
| **lease** | a local slice of a global counter; the hot path checks locally and syncs to the shared store on refill. |
| **D_safety** | config: the max delegation depth allowed, a runaway-recursion guard (e.g. 8). |
| **reserve** | config: the budget floor below which no new sub-agent is spawned, e.g. `max(reserve_micros, 0.1 × budget)`. |

## Key state and methods

State the ledger holds (per run), and how the derived values are computed:

```
state:
  depth: dict[run_id -> int]          # delegation depth, set once at open_run
  spent[(budget, key)] -> micros      # per-segment running total
  steps: dict[run_id -> int]
  inflight: dict[segment -> int]
  window: dict[run_id -> deque]       # (signature, result_hash, progress, ts, cum_cost)
  halted: set[run_id]

open_run(run_id, parent_run):         # depth stored once, O(1) read, never walk the chain
    depth[run_id] = depth[parent_run] + 1  if parent_run else 0

depth(run)        = depth.get(run, 0)
budget_left(run)  = limit(run) - spent(run)
velocity(run, M)  = (cum_now - cum_{M events ago}) / M     # both ends read from window, O(1)
```

Delegation gate used by `delegation_cap` (budget is the primary gate, depth is the safety net):

```
allow_spawn(parent_run):
    return budget_left(parent_run) >= reserve
       and depth(parent_run) + 1 <= D_safety
    # otherwise REFUSE the spawn; the child's open_run sets its depth = depth(parent) + 1
```

## Prerequisite (not a policy)

**attribution** — tag every call with its owner (run, user, agent, tenant, tags), accumulate cost per segment, emit an OpenTelemetry GenAI span. It is the foundation every policy reads from, not a policy itself.

## LLD: purpose, detect, fix

The **purpose** column carries the design intent (so a static cap, a cost claim, or an always-on default is not assumed where it does not hold).

| Policy | Purpose | Detect (formula) | Fix (mechanism, low level) |
|---|---|---|---|
| `delegation_cap` | **Budget-gated spawn**, not a static cap (complex tasks legitimately reuse sub-agents) | `budget_left(run) < reserve` OR `depth(run) ≥ D_safety` | **REFUSE** the spawn; return a structured "budget low / depth limit" error so the parent finalizes with what it has. The hard gate is remaining budget; depth is only a runaway-recursion safety net. |
| `concurrency_cap` | **Infra shield** (memory, downstream rate), **not a cost lever** | `inflight(seg) ≥ max_concurrent` | Single process: **QUEUE** in a bounded semaphore (backpressure). Serverless/distributed: **REJECT** with a retryable 429 so the caller's backoff resubmits. Never hold an open request across a scalable container; never kill admitted work (that wastes tokens for no saving). |
| `tool_fix` | **Cheap defensive check** (catch a hallucinated tool name before the model burns an I/O round-trip) | `name ∉ registry` (O(1) hash) OR `¬valid(args, schema[name])`; track `fails(run)` | **INJECT** a synthetic tool result `{error, did_you_mean (edit-distance), available_tools}` instead of executing, so the model self-corrects. After K identical failures, **HALT**. |
| `context_compaction` | Default; needs a prompt-assembly hook | `est_input ≥ ctx_max` OR `est_input` rising over the window (estimate, never tokenize on the hot path) | **MUTATE** the outgoing prompt: (1) move volatile values below the static prefix to restore the prompt-cache discount, (2) dedup tool outputs by hash, (3) summarize only filler, pinning system prompt, schema, constraints, state. No hook → degrade to telemetry, never HALT. Full history stays in the store. |
| `cost_guard` | **POC: instruction-based minimization** (a hard output cap risks partial output → re-call → more cost) | `spent(seg)/limit ≥ 0.8` (edge-triggered) OR `(cum(run) − cum_{M ago})/M > slope` | If routing: elasticity check, then **DOWNGRADE** the next call. For minimization, **INJECT** a "keep output minimal" system instruction (and trim input via compaction) rather than a hard `max_output` cap. POC to confirm savings exceed the instruction's auxiliary cost. |
| `pre_call_worst_case` | Default (preventive ceiling) | `spent(run) + price(est_in) + price(max(out, default)) ≥ budget` | **MUTATE**: set `max_output` to the default cap if unset (priced cap = enforced cap), then **HALT** before dispatch if it would still breach. Unknown price fails closed; never price the model's physical max. |
| `output_runaway` | Default; **heals, never halts** (backstops own any stop) | n-gram repetition over the streamed visible output (`repeats ≥ R`, single-token domination, or tail-loop). Prevent most by setting frequency/presence penalties + a `max_output` cap on the original request | **CANCEL** the stream (hard-break) to stop the bleed; **RETRY** bounded with raised frequency/presence penalties, a tighter cap, and optional `logit_bias` on the looping tokens; if still degenerate after the bounded retries, **INJECT** a "generation degenerated" error to the agent and continue. No HALT — persistent failure is caught by `cost_budget` / `step_cap` / `progress_guard`. Hidden reasoning bloat is bounded by the enforced cap. |
| `cost_budget` | Default; **the guarantee** | `∃ budget B: spent(seg_B) ≥ limit_B` (local check vs the leased slice; refill from the global counter when low) | **HALT**: raise `Halt`, set the halted flag in the shared store; the IN connector refuses every later call (local cache + invalidation). Roll child cost into the parent first. Idempotent. |
| `step_cap` | **Optional / opt-in** (step count is task-dependent; budget is the universal backstop) | `steps(run) ≥ max_steps` (per recorded event; per run, not per period) | **HALT**. Good for predictable-trajectory workflows; in A2A the shared run sums both agents' steps. |
| `tool_output_cap` | **Strong** (cheap `len()` detect, auxiliary cost negligible vs feeding a huge payload) | estimate tokens with a **content-aware divisor**: `len/4` for natural-language text, `len/2.8` for JSON / structured / code (denser tokenization); trip if `est_tokens ≥ cap`. No tokenizer on the hot path; for unknown or structured content default to the smaller divisor (2.8) so a large payload is never under-counted | **INJECT**: offload the full payload to the store (handle); substitute a descriptor `{size, schema, count, handle}` plus an instruction to paginate or filter. Never feed back a sliced payload as whole. |
| `progress_guard` | Default; the last-resort unstick | **Tier 1 (in-path, deterministic):** domain progress signal if exposed (`max−min(progress_N) ≤ ε`); exact repeat `count_W(normalized signature, result_hash) ≥ K`; **SimHash** near-duplicate `Hamming(simhash(output), recent) ≤ d` to catch paraphrase loops; hang `now − last_ts > T` (tick). **Tier 2 (off-path, optional):** embedding semantic similarity, sampled/async, to confirm ambiguous stalls — feeds the dashboard, never the in-path stop | **INJECT** a deterministic factual correction from the evidence; increment a correction counter; **HALT** only after K corrections with no progress. Require an unchanged result, not just a repeated call. Pinned by compaction. |

## The connectors

**IN telemetry the Instrument layer must supply:** attribution dims, `cost_micros`, LLM `usage`, tool `signature` and `result` (or its length), delegate `rolled_up_cost`, the streaming output chunks, and call-admit/complete signals.

**OUT controls the apply layer must expose (seven):** `HALT` (stop + halted flag) · `CANCEL` (hard-break a stream) · `REFUSE` (block a spawn) · `REJECT`/`QUEUE` (429 or backpressure) · `MUTATE` (swap model, cap output, rewrite prompt) · `INJECT` (substitute a tool result, or add a message to the next input) · `RETRY` (re-issue with new params).

The breaker owns `HALT` and `CANCEL`; every other policy heals or bounds.

## Sources

- Rate limiting (token bucket vs sliding window, Redis Lua atomicity): https://blog.arcjet.com/rate-limiting-algorithms-token-bucket-vs-sliding-window-vs-fixed-window/ , https://redis.io/tutorials/howtos/ratelimiting/
- LLM output degeneration / repetition detection: https://arxiv.org/html/2512.04419v1
- Anthropic, effective context engineering: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- LangChain guardrails (loop break, inject correction): https://docs.langchain.com/oss/python/langchain/guardrails
