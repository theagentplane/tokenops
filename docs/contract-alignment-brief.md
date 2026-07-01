# TokenOps Contract Alignment Brief

**Purpose:** Single reference for proposed changes to `contract/contract.md` and
`contract/contract.py`, based on design discussions for TokenOps and future
Chronicle alignment.

**Audience:** Author/maintainer of the control-plane contracts.

**Status:** Draft for review — not yet applied to the repo.

**Related repos:**

- TokenOps: `tokenops/` (`contract/`, `src/tokenops/`, this doc)
- Chronicle (reference): `../chronicle` (`chronicle/boundary.py`, envelopes)

---

## 1. Executive summary

The current contract (Instrument → Attribute → Enforce, IN/OUT connectors,
`Event` / `LedgerView` / `Action`) remains the right skeleton. These proposals
**extend and clarify** it:

1. **Separate circuit breakers from policies** — HALT is not a policy action; it
   follows from budget breach (**Option A:** any exceeded budget ⇒ halt).
2. **Usage segments** — dimensional selectors over boundary telemetry; budgets
   and policies both key off the same dim vocabulary.
3. **Instrument at boundaries, not in the agent loop** — provider wrap for LLM;
   function/node boundaries for tools and delegation.
4. **Price in analyse, raw usage at edge** — preserve token dims; derive
   `cost_micros` in Attribute; edge keeps price-table cache for future
   `pre_call`.
5. **Permanent multi-scope budgets** — run, user, agent, tenant, period — not
   v1-only concepts.
6. **A2A halt propagation** — shared `run_id`, delegation rollup, cross-service
   breaker.
7. **Event vs Envelope** — one capture, two projections; decouple from
   Chronicle later, not in initial contract pass.
8. **v1 scope** — policies in config with corrective actions; **breaker halts
   LLM only**; meter tools/delegate for segments without halting them yet.

---

## 2. What stays from the existing contract

| Element | Keep |
|--------|------|
| Three modules | Instrument (measure) → Attribute (tag + ledger) → Enforce (decide + act) |
| Connectors | IN (`emit` / `TelemetrySource`) and OUT (`apply` / `AgentControls`) |
| Core shapes | `Usage`, `Attribution`, `ModelCall`, `ToolCall`, `Delegation`, `CallRequest`, `Signal`, `Action`, `Halt` |
| Cost in micro-dollars | Integer `cost_micros`; compare cost not raw tokens |
| Fail closed | Unknown model/price/condition blocks or flags |
| `Halt` extends `BaseException` | Out-of-band kill; halted flag on `run_id` |
| Extension points | `Detector`, `Policy` ABCs; new `Event` subtypes for new boundary kinds |
| OTel GenAI mapping | Tokens on the wire; cost remains TokenOps-specific |

---

## 3. Architectural decisions (permanent)

### 3.1 Module naming (conceptual alignment)

| Discussion term | Contract module |
|-----------------|-----------------|
| Instrument | Instrument + IN connector |
| Analyse and decide | Attribute + Enforce (`Detector` + `Policy`) |
| Act | OUT connector (`AgentControls.apply`) |

### 3.2 Circuit breaker ≠ policy

| Mechanism | Role | Outcomes |
|-----------|------|----------|
| **Circuit breaker** | Hard stop when usage exceeds segment budgets | **HALT** (LLM only in v1) |
| **Policy** | Corrective rules when segment + usage conditions match | `modify_budget`, `downgrade_model`, `throttle`, `pause`, `allow` — **not HALT** |

Breaker mode (locked): **Option A — any matching budget exceeded ⇒ halt** on
applicable boundaries (v1: `boundary_kind == llm`).

### 3.3 Usage segments (replacement for informal “slice kinds”)

A **usage segment** is a **named matcher** over boundary telemetry dimensions.
One event/run can match **many segments** simultaneously.

**Fixed dims (boundary-defined):**

- `run_id`, `user_id`, `tenant_id`, `agent`, `parent_run_id`
- `boundary_kind` (`llm`, `tool`, `delegate`, `custom`)
- `provider`, `model`
- `tool.name`, `tool.signature`
- `delegate.target_agent`, `delegate.child_run_id`
- `step`, `ts`

**Custom dims (user-defined):**

- `tags.*` (e.g. `corpus_profile`, `environment`, `deal_id`)
- `labels[]`

**Budgets** attach limits to segments (+ period + aggregate field).

**Policies** use:

- `applies_to` — segment matcher (does this policy apply to this run/event?)
- `trigger` — dim filters + usage state (e.g. % of budget, token sums)

Same dim DSL for both.

### 3.4 Budget scopes (permanent, not v1-only)

| Scope | Example |
|-------|---------|
| Per run | This pipeline invocation |
| Per user / tenant | Monthly org cap |
| Per agent | Default cap template for `research` |
| Per tag combination | `corpus_profile:leak` runs |
| Cross-agent (A2A) | Same `run_id` for research → summarize |

Multiple budgets can apply to one event; **any breach trips breaker** (Option A).

### 3.5 Instrumentation strategy

**Default (non-intrusive):**

1. **LLM:** `cp.wrap(client) -> T` on provider SDK (OpenAI, Anthropic, LangChain
   chat model) — not `@boundary` on agent methods.
2. **Owned tools:** `@boundary` or choke point on the **function** (e.g.
   `search()`, or `invoke` inside `StructuredTool.from_function`).
3. **Delegation:** `@boundary(kind="delegate")` on `delegate_summarize()` / A2A
   client.
4. **Framework OOTB tools:** instrument **ToolNode** or tool callbacks — not
   per-tool object wraps.

**Avoid as primary surface:** `on_step` callbacks inside agent reasoning loops.

**Tiers:**

1. Provider choke point (`complete()` / wrapped client)
2. Function/node boundary (tools, delegate, LangGraph nodes)
3. Custom `extract_input` / `extract_result` (power users)
4. OTel span processor (future, optional)

### 3.6 Raw usage vs pricing

| Layer | Responsibility |
|-------|------------------|
| **Boundary / IN connector** | Emit raw `Usage` + attribution dims + optional custom tags |
| **Attribute / Instrument** | Derive `cost_micros`; update segment budget accumulators |
| **Edge (future)** | Local read-only price-table cache for `pre_call` worst-case checks |

Do not require pricing on the agent machine; do require **raw usage** at
boundary so repricing and audit remain possible.

### 3.7 Event vs Envelope

| Shape | Consumer | Content |
|-------|----------|---------|
| **Event** (TokenOps) | Breakers, policies, ledger hot path | Lean: usage, cost, attr, step |
| **Envelope** (Chronicle) | Replay, regression, judge | Rich: full prompts, RAG, graph state |

**One boundary crossing → telemetry record → projections.**

Decouple shared boundary package from Chronicle **later**; align shapes now.

### 3.8 Delegation and A2A

- Delegation is a **graph edge** but an **instrumented crossing** (`Delegation`
  event).
- Same `run_id` across research → summarize; child LLM usage rolls into parent
  segment budgets.
- **Breaker propagation:** halted `run_id` ⇒ IN connector on every agent refuses
  further LLM (and eventually delegate) calls.
- Contract fields: `Attribution.parent_run`, `Delegation.rolled_up_cost_micros`,
  shared halt flag keyed by `run_id`.

### 3.9 v1 scope (implementation, not contract permanence)

| In v1 contract/schema | Defer implementation |
|----------------------|----------------------|
| Usage segment DSL | Soft/async policies with overspend tolerance |
| Multi-dimensional budgets + Option A breaker | `pre_call` worst-case gate |
| Policies: `applies_to`, `trigger`, corrective actions | Halt on tool/delegate |
| Breaker: halt on LLM only | Full distributed halt store |
| Meter tools/delegate for segments | Chronicle envelope fan-out |
| `cp.wrap(client)` for LLM | Per-framework LLM object wraps |

---

## 4. Proposed contract additions

### 4.1 New first-class concepts

```text
TelemetryRecord   — dims + usage emitted at every boundary crossing
UsageSegment      — matcher over dims (registry or inline)
Budget            — segment + period + limit + aggregate field
CircuitBreaker    — any_budget_exceeded → HALT (configurable applies_to)
Policy            — applies_to segment + trigger + action (no halt)
```

### 4.2 Telemetry record (boundary emission)

```json
{
  "boundary_kind": "llm",
  "run_id": "run-abc",
  "user_id": "alice",
  "tenant_id": "acme",
  "agent": "research",
  "parent_run_id": null,
  "step": 3,
  "ts": 1719000000.0,

  "llm": { "provider": "openai", "model": "gpt-4o-mini" },
  "tool": { "name": "search", "signature": "sha256:…" },
  "delegate": { "target_agent": "summarize", "child_run_id": "run-abc" },

  "usage": {
    "input_tokens": 1200,
    "output_tokens": 150,
    "cached_tokens": 800,
    "reasoning_tokens": 0
  },

  "cost_micros": 4500,

  "tags": {
    "corpus_profile": "healthy",
    "environment": "dev"
  },
  "labels": ["experiment-v2"]
}
```

Only the block matching `boundary_kind` is required per event.

### 4.3 Usage segment matcher

```json
{
  "segment_id": "pipeline_llm_run",
  "match": {
    "all": [
      { "dim": "run_id", "op": "eq", "value": "{{ run_id }}" },
      { "dim": "boundary_kind", "op": "eq", "value": "llm" }
    ]
  }
}
```

```json
{
  "segment_id": "alice_research_leak",
  "match": {
    "all": [
      { "dim": "user_id", "op": "eq", "value": "alice" },
      { "dim": "agent", "op": "eq", "value": "research" },
      { "dim": "tags.corpus_profile", "op": "eq", "value": "leak" }
    ]
  }
}
```

Supported ops (minimum): `eq`, `neq`, `in`, `not_in`, `exists`, `gt`, `lt`,
`gte`, `lte`, `prefix`.

### 4.4 Budget

```json
{
  "budget_id": "research_run_llm_cap",
  "segment": {
    "all": [
      { "dim": "run_id", "op": "eq", "value": "{{ run_id }}" },
      { "dim": "agent", "op": "eq", "value": "research" },
      { "dim": "boundary_kind", "op": "eq", "value": "llm" }
    ]
  },
  "limit_micros": 500000,
  "period": "run",
  "aggregate": "sum",
  "field": "cost_micros"
}
```

```json
{
  "budget_id": "alice_monthly_llm",
  "segment": {
    "all": [
      { "dim": "user_id", "op": "eq", "value": "alice" },
      { "dim": "boundary_kind", "op": "eq", "value": "llm" }
    ]
  },
  "limit_micros": 100000000,
  "period": "calendar_month",
  "aggregate": "sum",
  "field": "cost_micros"
}
```

### 4.5 Circuit breaker (not policy)

```json
{
  "breaker_id": "default_llm_halt",
  "mode": "any_budget_exceeded",
  "applies_to": {
    "dim": "boundary_kind",
    "op": "eq",
    "value": "llm"
  },
  "on_trip": "halt",
  "propagate": {
    "a2a": true,
    "key": "run_id"
  }
}
```

**Semantics:** After each LLM boundary crossing, update all matching budget
accumulators; if **any** budget is over limit, trip breaker → `Halt` through OUT
connector; set halted flag on `run_id`.

### 4.6 Policy (corrective — no halt)

```json
{
  "policy_id": "leak_profile_budget_bump",
  "version": 1,
  "enabled": true,
  "precedence": 100,

  "applies_to": {
    "all": [
      { "dim": "tags.corpus_profile", "op": "eq", "value": "leak" },
      { "dim": "agent", "op": "eq", "value": "research" }
    ]
  },

  "trigger": {
    "all": [
      {
        "budget_ref": "research_run_llm_cap",
        "usage_pct": { "op": "gte", "value": 0.8 }
      }
    ]
  },

  "action": {
    "type": "modify_budget",
    "budget_id": "research_run_llm_cap",
    "delta_micros": 500000,
    "reason": "Leak profile — extend run cap before hard stop"
  },

  "execution": {
    "mode": "sync",
    "cooldown": "0s"
  }
}
```

**Allowed action types (permanent schema; v1 may implement subset):**

- `modify_budget` — changes budget limit (affects breaker thresholds)
- `downgrade_model` — agent + target model
- `throttle` — `retry_after_s`
- `pause` — human review
- `allow` — explicit no-op

**Explicitly excluded:** `halt` (owned by breaker).

**Future:** async policy execution with `overspend_tolerance_micros` (discussed,
not locked).

### 4.7 Policy precedence

When multiple policies match, apply by ascending `precedence` (lower number =
higher priority) unless contract writer prefers explicit `conflict_resolution`
enum — **needs alignment with contract author**.

---

## 5. Changes to existing contract types

### 5.1 `Attribution` — extend

```python
@dataclass(frozen=True, kw_only=True)
class Attribution:
    user: str
    agent: str
    run_id: str
    parent_run: str | None = None
    tenant_id: str | None = None          # NEW
    tags: Mapping[str, str] = ...         # NEW — custom segment dims
    labels: Sequence[str] = ...           # NEW
```

### 5.2 `Usage` — extend (align with OTel extensions)

```python
cached: int = 0
reasoning: int = 0
# optional: provider-specific extensions dict
```

### 5.3 `Delegation` — clarify semantics

- Record on A2A response, not only on request.
- `rolled_up_cost_micros` = sum of child LLM (and eventually tool) usage under
  shared `run_id`.

### 5.4 `ActionKind` — HALT for breaker only

**Proposal:** `ActionKind.HALT` remains the OUT connector signal for breakers
only; policies emit other kinds. Document that **policies must not emit HALT**.

Alternatively: breaker raises `Halt` exception directly without going through
`Policy.decide` — **needs author decision**.

### 5.5 `Detector` vs breaker vs policy

| Component | Responsibility |
|-----------|----------------|
| **Budget accumulator** | Attribute layer — O(1) per segment per period |
| **Circuit breaker** | After each relevant boundary — compare accumulators to limits |
| **Detector** | Optional signals (loops, velocity, anomalies) → **Policy** |
| **Policy** | Corrective actions only |

Clarify in contract whether breakers are a separate module or part of Enforce.

### 5.6 `ControlPlane` / IN connector

```python
def wrap(self, client: T) -> T:
    """LLM client proxy — primary instrumentation for provider objects."""

def crossing(
    self,
    boundary_id: str,
    kind: str,
    fn: Callable[..., Any],
    *,
    tags: Mapping[str, str] | None = None,
) -> Callable[..., Any]:
    """General boundary — function or method decoration."""
```

`on_step()` remains brownfield adapter, not the primary API.

---

## 6. Instrumentation ↔ test bench mapping

| Location today | Boundary kind | v1 breaker? |
|----------------|---------------|-------------|
| `providers/openai.py` `chat()` | `llm` | Yes (wrap here) |
| `agents/research/tools/core.py` `search()` | `tool` | No (meter only) |
| `a2a/client.py` `delegate_summarize()` | `delegate` | No (meter + rollup) |
| Summarize agent LLM | `llm` | Yes |
| Streamlit `corpus_profile` | `tags.corpus_profile` | Via segment budgets |

---

## 7. Chronicle alignment (future)

| TokenOps | Chronicle (today) |
|----------|-------------------|
| Boundary crossing | `@boundary` decorator |
| Telemetry record | Envelope |
| Usage segment | Implicit in envelope metadata + tags |
| Replay | Not TokenOps concern |

**Decision:** Same crossing concept; **do not import Chronicle in contract
now**. Optional shared package later.

Chronicle gaps noted for author awareness:

- `@boundary` LLM path may not populate `token_usage` (capture/LangGraph path
  does).
- High-level `@boundary("agent", kind="llm")` on simulated agents ≠ provider
  metering.

---

## 8. Open questions for contract author

1. **Breaker placement:** separate `CircuitBreaker` type vs Enforce submodule
   vs raised `Halt` outside `Policy.decide`?
2. **HALT in `ActionKind`:** keep for breaker only, or breaker bypasses `Action`
   entirely?
3. **Policy precedence:** numeric precedence vs segment specificity vs explicit
   priority field?
4. **Budget period rollover:** calendar month vs rolling 30d — schema support
   now?
5. **pre_call:** include in contract schema now as optional, or defer?
6. **Tool/delegate halt:** schema supports `applies_to: tool | delegate`; v1
   implements LLM only — OK?
7. **Custom dims:** `tags.*` only, or arbitrary nested paths?
8. **Event vs TelemetryRecord:** extend `Event` or new type that projects to
   `Event` for Enforce?

---

## 9. Suggested contract file changes (checklist)

| File | Action |
|------|--------|
| `contract/contract.md` | Add sections: Usage segments, Budgets, Circuit breakers, Policies, A2A propagation, Instrumentation tiers, Event vs Envelope |
| `contract/contract.py` | Add dataclasses: `UsageSegment`, `Budget`, `CircuitBreaker`, `Policy`; extend `Attribution`, `Usage` |
| `contract/budget.schema.json` | NEW — budget + segment matcher |
| `contract/policy.schema.json` | NEW — policy applies_to / trigger / action |
| `contract/breaker.schema.json` | NEW — Option A breaker config |
| `contract/telemetry.schema.json` | NEW — boundary telemetry record |
| `contract/integration-example.py` | Update: wrap provider, segment budgets, breaker trip |

---

## 10. Conversation lineage (for traceability)

Topics covered across design sessions:

- Test bench architecture, A2A servers, Streamlit UI, governance deferred
- Contract folder explanation (Instrument / Attribute / Enforce)
- Telemetry surfacing, brownfield vs greenfield, framework agnosticism
- `cost_micros` edge vs analyse; delegation as edge + event
- Event vs Envelope split; object vs method (`cp.wrap`)
- First principles (instrument / analyse / act)
- Permanent budget scopes; A2A circuit breakers; v1 LLM-only halt with policy
  support
- Halt from breaker not policy; usage segments; Option A budget overlap
- Chronicle repo parallel exploration; boundary as shared primitive (decouple
  later)

---

*Share this document with the contract author before modifying `contract/`.*
