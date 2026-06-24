# TokenOps Technical Governance Plan
 
## 1. What it governs: the run, not the request
 
TokenOps governs the **resource axis**: the tokens and compute a *run* consumes, and the behaviors that drive it (loops, context decay, fan-out). The unit is the **run** (`run_id`): all model, tool, and delegation calls of one task, across one or more agents, with child runs rolled up.
 
| Layer | Sees | Can govern |
|---|---|---|
| AI gateway (proxy) | independent requests | per-request budget, rate, routing |
| **TokenOps (in-process)** | the **run**: step sequence, context, fan-out | loops, context decay, fan-out, per-customer cost |
 
> A **request** is one model call (prompt in, completion out); a **run** is the whole agent task, many calls plus tools and delegations. A gateway sees requests one by one, so it can cap or route each; it can't see that calls repeat (a loop) or that context grows across them, because that lives in the run.
 
> Spend caps alone are commoditizing inside gateways. The defensible layer is run-aware **behavioral** governance, which a request-level proxy is blind to.
 
> **Why it can't be bypassed:** out-of-band control, in-path enforcement. The policy lives outside the agent (it can't rewrite it), but the check sits in the call path (it stops spend before it lands).
 
## 2. Architecture
 
```
            data plane: your agent (unchanged)
                       │  every call
              emit (IN)│           ▲ apply (OUT): steer or stop
                       ▼           │
   ┌───────────────────────────────────────────────┐
   │                control plane                   │
   │  Instrument  ──►  Account  ──►  Enforce         │
   │  price + tag      ledger        ├─ steer (cheaper / unstick)
   │                                 └─ halt  (breaker: the only stop)
   └───────────────────────────────────────────────┘
```
 
| Module | Job |
|---|---|
| Instrument | price each call, stamp the owner at the boundary |
| Account | per-segment ledger: running totals + per-run window + live counters |
| Enforce | circuit breaker (only stop) + active steering |
 
Every call is tagged with `run / user / agent / tenant / tags`. Budgets and policies attach along `global → tenant → user → agent → run`; one call matches many, most specific wins, any breach trips.
 
## 3. Policies
 
> **Four failure modes:** **Spend** (runaway cost) · **Stuck** (loops, stalls, hangs) · **Decay** (context rot) · **Fan-out** (parallel explosion). Attribution is the always-on base.
 
> **Design rule:** every policy is deterministic (no model in the path) and **acts**. It either **Heals** (recovers in flight), **Bounds** (caps or refuses, run continues), or **Stops** (halts). No passive alerts.
 
Rows are in **execution order**: the pre-call gate, then the stream, then after the call. A hard stop wins over steers; the cheaper fixes run before `progress_guard` escalates, because clearing decayed context often cures the stall.
 
| When | Policy | Mode | Detect (when it fires) | Fix | Acts |
|---|---|---|---|---|---|
| ~~pre-call~~ | ~~`delegation_cap`~~ | ~~fan-out~~ | ~~an agent spawns sub-agents too deep, or too many at once~~ | ~~refuse the new sub-agent~~ | ~~Bound~~ *Removed — depth-based spawn limits dropped; see `concurrency_cap` and spend breakers.* |
| pre-call | `concurrency_cap` | fan-out | too many calls run at the same time | hold the extra ones, or reject so the caller retries | Bound |
| pre-call | `tool_fix` | stuck | the agent calls an unknown tool, or with bad arguments | return a clear error so it self-corrects; stop after repeated failures | Heal |
| pre-call | `context_compaction` | decay | the prompt is large or steadily growing | shrink it: restore cache order, drop duplicates, summarize filler (keep the important parts) | Heal |
| pre-call | `cost_guard` | cost lever | spend rising fast, or past 80% of budget | switch to a cheaper model (if it fits), or shrink the prompt and cap output | Heal |
| pre-call | `pre_call_worst_case` | spend | the next call could, worst case, blow the budget | cap the call; stop if it still would | Stop |
| stream | `output_runaway` | spend | the output keeps repeating the same text | cancel the stream; nudge once; stop if it repeats | Heal, then Stop |
| observe | `cost_budget` | spend | the run hits its spend limit | stop the run, block further calls | Stop |
| observe | `step_cap` | spend | the run takes more steps than allowed | stop the run | Stop |
| observe | `tool_output_cap` | fan-out | one tool returns a payload too big for the context | store it, hand back a summary plus "fetch it in pages" | Heal |
| observe | `progress_guard` | stuck | the agent repeats the same call and result, makes no progress, or hangs | tell it plainly why it is stuck; stop as a last resort | Heal, then Stop |
| always | `attribution` | base | always on | tag and total every call per customer; emit a standard span | Telemetry |
 
**When a policy stops a run:** a stop halts spend and preserves state (cost so far, reason, snapshot). It never destroys the run. Resume is delegated and always deliberate. TokenOps provides the snapshot, and the runtime or a human decides whether to resume; never automatic.
 
## 4. V2
 
Smart dashboard: live per-customer cost, run health, a halt and steer feed, and the observe-to-enforce recommender. Reads the ledger, off the hot path.
