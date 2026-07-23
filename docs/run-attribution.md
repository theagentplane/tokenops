# Run attribution and registration

Source of truth for how workflow identity, trace dims, and boundary telemetry
are separated and wired into the control plane.

Related: `docs/architecture.md`, `docs/governance-policy.md`, #5 (composite segment matchers).

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

- **Registration is preferred** before boundary telemetry so cross-agent budgets share one `run_id`.
- **Duplicate register** for the same `run_id` → error.
- **Entry agent missing `X-TokenOps-Run-Id`** → `tokenops_run` registers via
  `ControlPlaneClient` (plane `POST /v1/runs` or embedded Store).
- **Downstream missing `X-TokenOps-Run-Id`** → soft path: auto-register an `unattributed` run,
  log `tokenops.missing_run_id` / `cross_agent_attribution_broken`, and still govern locally.
- **Unknown `run_id` on resolve** → fail closed (`RunNotRegisteredError`).
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
1. Entry (research / planner)
     tokenops_run → ControlPlaneClient.register_run (if UI omitted run_id)
     span s1: service=entry, parent=null
     boundaries → Observation → governor.observe

2. Delegate
     headers: X-TokenOps-Run-Id, X-TokenOps-Parent-Span-Id=s1 (ambient merge)
     child tokenops_run joins run_id (no register)
     span s2: service=child, parent=s1
     child LLM/tool spend → shared ledger (no parent cost rollup)

3. Unregistered run_id at boundary
     resolve_run → RunNotRegisteredError → fail closed
```

Same `run_id` across the workflow. New `span_id` per agent hop.

---

## Ingest seam (Tisha)

Ingest builds a ledger `Attribution` for `segment_key_for` inside `tokenops_run`
(and boundary ingest):

- `run_id` ← registration
- `agent` ← boundary `service`
- `tags` ← `{**user_dims, "intent": intent}`

Policies and ledger stay unchanged until composite segment matchers land (#5).

---

## API (v1)

```python
# Happy path — integrators
from tokenops import ControlPlaneClient, instrument_app, tokenops_run

with tokenops_run(client=client) as bound:
    ...  # bound.registration, bound.attr, bound.governor, bound.controls

# Plane / Store (control plane)
store.register_run(RunRegistration(run_id, intent="", user_dims={}))
store.resolve_run(run_id)  # raises RunNotRegisteredError

step_to_observation(step, attr, *, service, boundary_tags) -> Observation
```

---

## Boundary annotation (`@boundary`)

Use Chronicle's decorator directly
([theagentplane/chronicle](https://github.com/theagentplane/chronicle)).
TokenOps registers a crossing hook so LIVE crossings feed the Governor when
governance context is bound:

```python
from chronicle import boundary, get_session, ReplayPlan
from chronicle.session import reset_session
from tokenops import tokenops_run
from tokenops.control import install_crossing_hook

install_crossing_hook()  # also done by instrument_app / tokenops.init

@boundary("search", kind="tool")          # Chronicle decorator
def search(query: str) -> SearchResult: ...

reset_session().begin_trace(run_id)       # Chronicle session
with tokenops_run(client=client) as bound:  # binds governor for crossing hook
    search("pricing")
```

| Chronicle | TokenOps |
|-----------|----------|
| `session.record_envelope` | Chronicle package |
| REPLAY + STUB / cut-point LIVE | retained via `ReplayPlan` |
| `session.on_crossing` | `control/crossing.py` → `governor.observe` when bound |

## Run registration API (#2)

**Register first** (entry agent via plane — UI may omit and let the entry agent do this):

```
POST /v1/runs
{ "run_id": "optional", "intent": "", "user_dims": {} }
→ 201 { "run_id": "...", "status": "registered" }
```

**Then execute** (entry may register itself when the header is absent):

```
POST /v1/tasks
# X-TokenOps-Run-Id optional on entry; required (propagated) on downstream hops
# UI sends task only — intent/mode from agent instrument_app / tokenops_run kwargs
{ "task": "...", "bench": { "corpus_profile": "healthy" } }
```

Implemented in `control/http.py` (`mount_run_registration`) on the plane app
(`tokenops.server`); agents mount the same route only when ``TOKENOPS_URL`` is
unset. Entry agents use ``tokenops_run`` → ``ControlPlaneClient.register_run``.
Downstream handlers resolve registration only.

## Cross-process ledger (spend + halt)

Agents pass the shared ``Store`` into ``build_governor(..., store=store)`` (or use
``TOKENOPS_URL`` + plane). Spend, inflight, and halt accumulators live in SQLite
``ledger_*`` tables so every hop on one ``run_id`` enforces the same ``run_llm_cap``.
Step windows stay per-process.

## Out of scope (this doc)

- Composite segment AND matchers → #5
- Distributed halt revocation / gateway tokens → future
- **`corpus_profile`** — test-bench agent config under ``payload["bench"]`` only; not registration or attribution
