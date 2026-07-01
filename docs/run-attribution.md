# Run attribution and registration

Source of truth for how workflow identity, trace dims, and boundary telemetry
are separated and wired into the control plane.

Related: `docs/instrumentation-contract.md` (ingest seam), `docs/shared-ledger-comparison.md` (cross-process spend), #5 (composite segment matchers).

---

## Two layers

| Layer | When set | Mutable? | Purpose |
|-------|----------|----------|---------|
| **Run registration** | Explicit call before any telemetry | No | Segment × policy matching |
| **Boundary observation** | Each instrumented crossing | Per node | Span graph + node config |

### Run registration (SQLite: `run_registrations`)

Frozen for the whole `run_id`:

| Field | Source | Notes |
|-------|--------|-------|
| `run_id` | Client or entry service | Only universal OOTB identity |
| `intent` | Server at session start | Empty string if omitted; maps to segment × policy |
| `user_dims` | Caller | Opaque key/value tags (`Country`, `IsFortune500`, …) |

Rules:

- **Registration is required** before any boundary emits telemetry.
- **Duplicate register** for the same `run_id` → error.
- **Missing registration** on resolve → fail closed.
- No `triggered_by` first-class field — use `user_dims["user_id"]` if needed.
- **`corpus_profile` is not a control-plane dim** — test-bench agent config only.

### Boundary observation

Every crossing carries:

| Field | Layer |
|-------|-------|
| `run_id` | From registration (ambient) |
| `intent`, `user_dims` | Copied from registration (read-only) |
| `span_id`, `parent_span_id` | Span graph |
| `service` | **Mandatory** — which agent/service owns this span |
| `boundary_tags` | Node specifics: `node_type`, `provider`, `model`, `tool`, … |

Trace dims answer *who / why*. Boundary tags answer *what this node is doing*.

---

## Propagation (stack-agnostic)

### Wire (HTTP)

```
X-TokenOps-Run-Id: <run_id>
X-TokenOps-Parent-Span-Id: <span_id>   # on delegate / downstream calls
```

Entry service **registers** the run. Downstream services **resolve only** (never
re-register).

### In-process (Python)

`contextvars` hold the active registration + span for the request. Boundaries and
ingest read ambient context — handlers do not pass dims as arguments.

Code: `control/context.py`, `control/attribution.py`.

---

## Flow

```
1. Entry (research)
     register_run(run_id, intent, user_dims)
     span s1: service=research, parent=null
     boundaries → Observation → governor.observe

2. Delegate
     headers: X-TokenOps-Run-Id, X-TokenOps-Parent-Span-Id=s1
     summarize resolves run_id (no register)
     span s2: service=summarize, parent=s1

3. Unregistered run_id at boundary
     resolve_run → RunNotRegisteredError → fail closed
```

Same `run_id` across the workflow. New `span_id` per agent hop.

---

## Ingest seam (Tisha)

Ingest builds a legacy `Attribution` for `segment_key_for` via
`build_attribution(registration, service=…)`:

- `run_id` ← registration
- `agent` ← boundary `service`
- `tags` ← `{**user_dims, "intent": intent}`

Policies and ledger stay unchanged until composite segment matchers land (#5).

---

## API (v1)

```python
store.register_run(RunRegistration(run_id, intent="", user_dims={}))
store.resolve_run(run_id)  # raises RunNotRegisteredError

attribution.begin_run(store, headers, payload, service="research", entry=True)
attribution.require_run(store)  # boundaries / ingest

build_attribution(reg, service="research") -> Attribution
step_to_observation(step, attr, *, service, boundary_tags) -> Observation
```

---

## Boundary annotation (`@boundary`)

Chronicle-compatible package: `tokenops.chronicle` (mirrors
[theagentplane/chronicle](https://github.com/theagentplane/chronicle)).

```python
from tokenops.chronicle import boundary, reset_session, ReplayPlan, get_session
from tokenops.control import governance_scope

@boundary("search", kind="tool")          # same signature as Chronicle
def search(query: str) -> SearchResult: ...

reset_session().begin_trace(run_id)       # Chronicle session
with governance_scope(governor, attr):    # TokenOps extension → governor.observe
    search("pricing")
```

| Chronicle | TokenOps |
|-----------|----------|
| `session.record_envelope` | retained in `tokenops.chronicle` |
| REPLAY + STUB / cut-point LIVE | retained via `ReplayPlan` |
| — | `governor.observe` when `governance_scope` is bound |

## Run registration API (#2)

**Register first** (entry only):

```
POST /v1/runs
{ "run_id": "optional", "intent": "", "user_dims": {} }
→ 201 { "run_id": "...", "status": "registered" }
```

**Then execute** (all agents):

```
POST /v1/tasks
X-TokenOps-Run-Id: <run_id>
{ "task": "...", "bench": { "corpus_profile": "healthy" } }
```

Implemented in `a2a/server.py` (`register_run` when `store=` is passed to `create_a2a_app`).
Research native server: `agents/research/native/server.py` task handler resolves only.

## Cross-process ledger (spend + halt)

A2A servers pass the shared ``Store`` into ``build_governor(..., store=store)``. Spend,
inflight, and halt accumulators live in SQLite ``ledger_*`` tables so research and summarize
enforce the same ``run_llm_cap`` on one ``run_id``. Step windows stay per-process.

Research refuses to delegate when ``run_llm_cap`` headroom is exhausted.

## Out of scope (this doc)

- Composite segment AND matchers → #5
- Distributed halt revocation / gateway tokens → future
- **`corpus_profile`** — test-bench agent config under ``payload["bench"]`` only; not registration or attribution
