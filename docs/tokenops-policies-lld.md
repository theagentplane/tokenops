# TokenOps Policies LLD

## Glossary 

| Term | Meaning |
|---|---|
| **segment** | a grouping a budget/policy attaches to: the value of one dimension (run, user, agent, tenant, or a tag). One event belongs to several segments at once. |
| **inflight(seg)** | how many calls for that segment have started but not yet returned **right now** (concurrent calls in progress). |
| **budget_left(budget, segment_key)** | remaining budget for one accumulator: `limit − spent[(budget_id, segment_key, period)]`. |
| **window** | append-only list of **boundary steps** for the run (unbounded). Policies read a bounded tail via `recent(run, W)` when they need a sliding view. |
| **boundary step** | one completed `@boundary` crossing — the lean TokenOps projection of a Chronicle Envelope on the enforce hot path. |
| **signature** | a stable hash of (tool name, args). |
| **result_hash** | a hash of the tool's result, to tell if a repeated call returned the same thing. |
| **SimHash** | a 64-bit fingerprint of a text; two texts are near-duplicates if their fingerprints' Hamming distance is small. Deterministic, no model. |
| **logit_bias** | a per-token bias added to the model's output scores before sampling, to make specific tokens more/less likely or ban them; used on a retry to stop the model repeating the tokens it was looping on. |
| **frequency / presence penalty** | decoding parameters that lower the probability of tokens already used (frequency) or already present (presence); set on the request to prevent or recover from degenerate, repeating output. |
| **est_input** | estimated input tokens for the next call (prev call's input tokens, or chars/4). Avoids tokenizing on the hot path. |
| **cum cost** | cumulative run spend (`cum_spent_micros`) stamped on each boundary step **by Attribute** after pricing and accumulator update — not emitted at the boundary. |
| **lease** | a local slice of a global counter; the hot path checks locally and syncs to the shared store on refill. |
| ~~**reserve**~~ | ~~config: the budget floor below which no new sub-agent is spawned, e.g. `max(reserve_micros, 0.1 × budget)`.~~ *Removed with `delegation_cap`.* |

## Key state and methods

**`run_id` is the index, not a field inside run state.** Per-run ephemeral
state lives under `runs[run_id]`. Spend and inflight counters live in separate
accumulator maps because one event can match **many** budgets/segments at once.

**`spent` vs `inflight`:**

| Counter | Keyed by | What it means |
|---------|----------|---------------|
| **`spent`** | **Budget accumulator** `(budget_id, segment_key, period)` | Running total for a **budget** bound to a resolved segment (e.g. this run's LLM cap, this tenant's monthly cap). One event can increment several accumulators. |
| **`inflight`** | **Segment key** (e.g. `run:run-abc`, `tenant:acme`) | Concurrent calls in flight for whatever dimension `concurrency_cap` scopes to — **not** per budget. Increment on admit, decrement on complete. |

A **segment** is the resolved value of a budget/policy matcher (run, user,
tenant, agent, tag combo). A **budget** attaches a limit to that matcher;
`spent` is always budget-scoped. `inflight` is segment-scoped for concurrency
only.

State the ledger holds, and how derived values are computed:

```
ledger:
  runs: dict[run_id -> RunState]
  spent: dict[(budget_id, segment_key, period) -> micros]
  inflight: dict[segment_key -> int]

RunState:                             # no run_id field — the dict key is the run
  steps: int
  window: list[BoundaryStep]          # append-only, unbounded — one step per boundary crossing
  halted: bool
  halt_reason: str | None

open_run(run_id, parent_run):
    runs[run_id] = RunState(steps=0, window=[], halted=False)

# Attribute.record() after each boundary crossing:
#   1. price raw usage (LLM only) → update spent[(budget_id, segment_key, period)]
#   2. append BoundaryStep with cum_spent_micros = current run total from accumulators
#   3. increment steps

budget_left(budget_id, segment_key, period)
    = limit(budget_id) - spent[(budget_id, segment_key, period)]
velocity(run, M)  = (window[-1].cum_spent_micros - window[-M].cum_spent_micros) / M
recent(run, W)    = runs[run].window[-W:]   # bounded tail over unbounded history
```

In single-process mode, `runs[run_id].halted` is the kill switch. In
distributed A2A, that field is backed by the shared store (same shape, different
backend) so every agent's IN connector refuses further calls on a halted run.

## Boundary step (window entry)

Each step in `runs[run_id].window` is one **completed boundary crossing** — the same
concept Chronicle's `@boundary(boundary_id, kind=…)` records as an Envelope, projected
lean for enforce.

**Chronicle (reference)** wraps a function, captures `InputState` + `ActionResult`,
stores a rich Envelope (`node_id`, `boundary_kind`, full prompt, completion,
`token_usage`). TokenOps does **not** store the full envelope on the hot path.

**Layer split:**

| Layer | Responsibility |
|-------|----------------|
| **Instrument / IN** | At boundary exit: `input`, `output`, `tags`, `node_type`, raw `usage` (LLM only). No `cost_micros`. |
| **Attribute / Account** | Price LLM `usage` → update `spent[…]` accumulators → append `BoundaryStep` with `cum_spent_micros`. |

```python
BoundaryStep:
  step: int                           # monotonic per run (= len(window) + 1)
  ts: float
  node_type: "llm" | "tool" | "delegate"   # Chronicle boundary_kind
  boundary_id: str                    # Chronicle node_id, e.g. "research.chat", "search"
  input: object                       # lean — see shapes below
  output: object
  tags: dict[str, str]                # corpus_profile, environment, …
  usage: Usage | None                 # LLM only: raw provider tokens (input/output/cached/reasoning)
  signature: str | None               # tool: stable hash of (name, args) — from input
  result_hash: str | None             # tool: hash of output — for repeat detection
  cum_spent_micros: int               # run total AFTER this step — written by Attribute, not Instrument
```

**`input` / `output` shapes by `node_type`:**

| `node_type` | `input` | `output` | `usage` |
|-------------|---------|----------|---------|
| **llm** | assembled prompt snapshot or lean proxy: `{ message_count, prompt_hash }` | `{ text, finish_reason }` or `{ tool_calls: [...] }` | provider token counts |
| **tool** | `{ name, args }` | tool result (or `{ result_hash, size }` if payload offloaded) | `None` |
| **delegate** | `{ target_agent, payload_summary }` | `{ status, child_run_id? }` | `None` — child LLM usage rolls up via separate llm steps / `rolled_up_cost` on delegate event |

Detectors derive hot-path fields from the step: `signature` / `result_hash` for loop
checks, `output.text` / SimHash for `progress_guard`, `usage.input` for
`context_compaction` (`est_input` ≈ last llm step's input tokens).

### Example: research → search → … → delegate → summarize

Research agent loop (`@boundary` on provider wrap + tool function), shared `run_id`
across A2A:

```json
{
  "step": 1,
  "ts": 1719000001.2,
  "node_type": "llm",
  "boundary_id": "research.chat",
  "input": { "message_count": 3, "prompt_hash": "sha256:a1b2…" },
  "output": { "tool_calls": [{ "name": "search", "arguments": { "query": "pricing API" } }] },
  "tags": { "corpus_profile": "leak", "agent": "research" },
  "usage": { "input": 820, "output": 45, "cached": 0, "reasoning": 0 },
  "signature": null,
  "result_hash": null,
  "cum_spent_micros": 1200
}
```


```json
{
  "step": 2,
  "ts": 1719000002.1,
  "node_type": "tool",
  "boundary_id": "search",
  "input": { "name": "search", "args": { "query": "pricing API" } },
  "output": { "snippet": "…", "completeness": 0.2 },
  "tags": { "corpus_profile": "leak", "agent": "research" },
  "usage": null,
  "signature": "sha256:search|pricing API",
  "result_hash": "sha256:…",
  "cum_spent_micros": 1200
}
```


```json
{
  "step": 7,
  "ts": 1719000045.0,
  "node_type": "delegate",
  "boundary_id": "delegate_summarize",
  "input": { "target_agent": "summarize", "findings_count": 6 },
  "output": { "status": "accepted" },
  "tags": { "agent": "research" },
  "usage": null,
  "signature": null,
  "result_hash": null,
  "cum_spent_micros": 38500
}
```


```json
{
  "step": 8,
  "ts": 1719000046.3,
  "node_type": "llm",
  "boundary_id": "summarize.chat",
  "input": { "message_count": 2, "prompt_hash": "sha256:c3d4…" },
  "output": { "text": "Summary of findings…", "finish_reason": "stop" },
  "tags": { "agent": "summarize" },
  "usage": { "input": 2400, "output": 180, "cached": 0, "reasoning": 0 },
  "signature": null,
  "result_hash": null,
  "cum_spent_micros": 45200
}
```

Steps 3–6 would repeat the llm→tool pattern while `corpus_profile: leak` keeps
completeness low. `cost_budget` reads `spent[…]` accumulators; `progress_guard`
reads `recent(run, W)` for repeated `(signature, result_hash)` pairs;
`cost_guard` velocity uses `cum_spent_micros` deltas across the unbounded window.

**Chronicle alignment (future):** one crossing → Chronicle Envelope (replay) +
TokenOps BoundaryStep (enforce). Same `boundary_id` + `node_type`; no import
required in v1.

## Prerequisite (not a policy)

**attribution** — tag every call with its owner (run, user, agent, tenant, tags), accumulate cost per segment, emit an OpenTelemetry GenAI span. It is the foundation every policy reads from, not a policy itself.

## LLD: purpose, detect, fix

The **purpose** column carries the design intent (so a static cap, a cost claim, or an always-on default is not assumed where it does not hold).

| Policy | Purpose | Detect (formula) | Fix (mechanism, low level) |
|---|---|---|---|
| ~~`delegation_cap`~~ | ~~**Budget-gated spawn**, not a static cap (complex tasks legitimately reuse sub-agents)~~ | ~~`budget_left(run) < reserve` OR `depth(run) ≥ D_safety`~~ | ~~**REFUSE** the spawn; return a structured "budget low / depth limit" error so the parent finalizes with what it has. The hard gate is remaining budget; depth is only a runaway-recursion safety net.~~ *Removed — depth-based delegation limits dropped; fan-out is handled by `concurrency_cap` and spend by `cost_budget` / `pre_call_worst_case`.* |
| `concurrency_cap` | **Infra shield** (memory, downstream rate), **not a cost lever** | `inflight(seg) ≥ max_concurrent` | Single process: **QUEUE** in a bounded semaphore (backpressure). Serverless/distributed: **REJECT** with a retryable 429 so the caller's backoff resubmits. Never hold an open request across a scalable container; never kill admitted work (that wastes tokens for no saving). |
| `tool_fix` | **Cheap defensive check** (catch a hallucinated tool name before the model burns an I/O round-trip) | `name ∉ registry` (O(1) hash) OR `¬valid(args, schema[name])`; track `fails(run)` | **INJECT** a synthetic tool result `{error, did_you_mean (edit-distance), available_tools}` instead of executing, so the model self-corrects. After K identical failures, **HALT**. |
| `context_compaction` | Default; needs a prompt-assembly hook | `est_input ≥ ctx_max` OR `est_input` rising over `recent(run, W)` (estimate from last llm step's `usage.input`, never tokenize on the hot path) | **MUTATE** the outgoing prompt: (1) move volatile values below the static prefix to restore the prompt-cache discount, (2) dedup tool outputs by hash, (3) summarize only filler, pinning system prompt, schema, constraints, state. No hook → degrade to telemetry, never HALT. Full history stays in the unbounded window. |
| `cost_guard` | **POC: instruction-based minimization** (a hard output cap risks partial output → re-call → more cost) | `spent(seg)/limit ≥ 0.8` (edge-triggered) OR velocity from `cum_spent_micros` over last M boundary steps | If routing: elasticity check, then **DOWNGRADE** the next call. For minimization, **INJECT** a "keep output minimal" system instruction (and trim input via compaction) rather than a hard `max_output` cap. POC to confirm savings exceed the instruction's auxiliary cost. |
| `pre_call_worst_case` | Default (preventive ceiling) | `spent(run) + price(est_in) + price(max(out, default)) ≥ budget` | **MUTATE**: set `max_output` to the default cap if unset (priced cap = enforced cap), then **HALT** before dispatch if it would still breach. Unknown price fails closed; never price the model's physical max. |
| `output_runaway` | Default; **heals, never halts** (backstops own any stop) | n-gram repetition over the streamed visible output (`repeats ≥ R`, single-token domination, or tail-loop). Prevent most by setting frequency/presence penalties + a `max_output` cap on the original request | **CANCEL** the stream (hard-break) to stop the bleed; **RETRY** bounded with raised frequency/presence penalties, a tighter cap, and optional `logit_bias` on the looping tokens; if still degenerate after the bounded retries, **INJECT** a "generation degenerated" error to the agent and continue. No HALT — persistent failure is caught by `cost_budget` / `step_cap` / `progress_guard`. Hidden reasoning bloat is bounded by the enforced cap. |
| `cost_budget` | Default; **the guarantee** | `∃ budget B: spent(seg_B) ≥ limit_B` (local check vs the leased slice; refill from the global counter when low) | **HALT**: raise `Halt`, set the halted flag in the shared store; the IN connector refuses every later call (local cache + invalidation). Roll child cost into the parent first. Idempotent. |
| `step_cap` | **Optional / opt-in** (step count is task-dependent; budget is the universal backstop) | `steps(run) ≥ max_steps` (per recorded event; per run, not per period) | **HALT**. Good for predictable-trajectory workflows; in A2A the shared run sums both agents' steps. |
| `tool_output_cap` | **Strong** (cheap `len()` detect, auxiliary cost negligible vs feeding a huge payload) | estimate tokens with a **content-aware divisor**: `len/4` for natural-language text, `len/2.8` for JSON / structured / code (denser tokenization); trip if `est_tokens ≥ cap`. No tokenizer on the hot path; for unknown or structured content default to the smaller divisor (2.8) so a large payload is never under-counted | **INJECT**: offload the full payload to the store (handle); substitute a descriptor `{size, schema, count, handle}` plus an instruction to paginate or filter. Never feed back a sliced payload as whole. |
| `progress_guard` | Default; the last-resort unstick | **Tier 1 (in-path, deterministic):** domain progress signal if exposed (`max−min(progress_N) ≤ ε`); exact repeat `count in recent(run,W) of (signature, result_hash) ≥ K`; **SimHash** near-duplicate on llm `output.text`; hang `now − last step ts > T` (tick). **Tier 2 (off-path, optional):** embedding semantic similarity, sampled/async — feeds the dashboard, never the in-path stop | **INJECT** a deterministic factual correction from the evidence; increment a correction counter; **HALT** only after K corrections with no progress. Require an unchanged result, not just a repeated call. Pinned by compaction. |

## The connectors

**IN telemetry the Instrument layer must supply:** attribution dims, `cost_micros`, LLM `usage`, tool `signature` and `result` (or its length), delegate `rolled_up_cost`, the streaming output chunks, and call-admit/complete signals.

**OUT controls the apply layer must expose (six active):** `HALT` (stop + halted flag) · `CANCEL` (hard-break a stream) · `REJECT`/`QUEUE` (429 or backpressure) · `MUTATE` (swap model, cap output, rewrite prompt) · `INJECT` (substitute a tool result, or add a message to the next input) · `RETRY` (re-issue with new params). ~~`REFUSE` (block a spawn)~~ *removed with `delegation_cap`.*

The breaker owns `HALT` and `CANCEL`; every other policy heals or bounds.

## Sources

- Rate limiting (token bucket vs sliding window, Redis Lua atomicity): https://blog.arcjet.com/rate-limiting-algorithms-token-bucket-vs-sliding-window-vs-fixed-window/ , https://redis.io/tutorials/howtos/ratelimiting/
- LLM output degeneration / repetition detection: https://arxiv.org/html/2512.04419v1
- Anthropic, effective context engineering: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- LangChain guardrails (loop break, inject correction): https://docs.langchain.com/oss/python/langchain/guardrails
