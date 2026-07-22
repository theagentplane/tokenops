# Principles

TokenOps manages token spend using a small set of rules that stay true regardless of model or framework.

## 1. Govern the run, not the request

| Unit | What it is |
|---|---|
| **Request** | One model call (prompt in, completion out) |
| **Run** | One user task — many calls, tools, and delegations, tied together by a `run_id` |

Spend caps on individual requests miss the failure modes that matter: recursive tool loops, context that grows every turn, and multi-agent fan-out. TokenOps accumulates cost and behavior signals across the whole run.

## 2. Measure, attribute, bound

Every governed crossing must answer three questions:

1. **How much** did this step cost? (measure)
2. **Whose** run is it — user, agent, tenant, tags? (attribute)
3. **What stops** the run before the invoice does? (bound)

If you cannot answer all three at runtime, you are reporting spend after the fact, not governing it.

## 3. You cannot bound by prediction alone

A static estimate set before the run is wrong on the tail. Agents are nondeterministic: the same prompt can produce different step counts and token totals. The only bound that holds is enforced **during** the run — watch spend and behavior as they accrue, then act.

## 4. Separate control plane from data plane

```
  data plane     →  agent logic (unchanged)
  control plane  →  meter, ledger, policies, actuators
```

The agent does the work. TokenOps meters each boundary crossing, updates the ledger, runs detectors, and applies actions (stop, steer, inject). The agent never owns the budget check.

## 5. Fail closed

Unknown price, missing registration, or an unhandled policy signal → **refuse**, not silent allow. A governance system that fails open is worse than no governance.

## 6. Deterministic policies, no model in the path

Every policy is a **detector** (read-only signal from the ledger) plus a **fix** (a concrete action). No LLM judges whether to halt. That keeps enforcement fast, testable, and predictable.

## 7. Act, don't alert

Policies **do something**: halt the run, cap the next call, inject a correction, reject backpressure, or reshape the prompt. Passive dashboards are for humans; the control plane is for the hot path.

## 8. Budget vs policy

| Concept | Role |
|---|---|
| **Budget** | A spend bucket with an optional cap (e.g. per run, per user, per tag) |
| **Policy** | A rule that watches the ledger and decides what to do |

Some policies link to a budget (`cost_budget`, `pre_call_worst_case`, `cost_guard`). Others use their own parameters (`step_cap`, `tool_fix`, …). Spend always flows into the ledger; policies react to what they see.

## 9. Registration before telemetry

Each run is **registered** once with stable dimensions (intent, customer tags). Every later crossing inherits that context. Telemetry without registration is rejected — attribution is explicit, not inferred from the first write.

## 10. Sticky halt

When a run is **halted**, it stays halted for the remainder of that run. The kill switch is checked before every subsequent call so a caught exception cannot resume unbounded spend.

---

## Four failure modes we optimize for

| Mode | Example | Policy families |
|---|---|---|
| **Spend** | Runaway cost, worst-case breach | `cost_budget`, `pre_call_worst_case`, `cost_guard`, `output_runaway` |
| **Stuck** | Same tool call with no progress | `progress_guard`, `tool_fix` |
| **Decay** | Context grows until quality collapses | `context_compaction` |
| **Fan-out** | Too many concurrent calls or huge tool payloads | `concurrency_cap`, `tool_output_cap` |
