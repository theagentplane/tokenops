# Design fix notes (TokenOps integration surface)

**Status:** done (agent-owned dims via instrument_app / tokenops_run)  
**Date:** 2026-07-23  
**Context:** Captured during beginner walkthrough; product/API direction, not yet implemented.

---

## 1. Run registration dims from agent definition, not UI

**Area:** `entry_task_run_scope` / `ControlPlaneClient.register_run` / A2A task payloads

### Problem

When the entry agent auto-registers a run (UI omits `X-TokenOps-Run-Id`), TokenOps reads `intent`, `user_dims`, and `mode` from the **HTTP task body** (`payload`) that the UI/client sent.

That couples attribution and governance mode to whatever the front-end chooses to pass. Callers can omit, spoof, or inconsistently set dims. The agent definition (config / service code) is the better source of truth for “what kind of run is this” and default mode.

### Desired behavior

- **UI / client:** sends the work (`task`, inputs). May still send *caller* identity if needed (e.g. `user_id`), but should not own run `intent` / governance `mode` by default.
- **Agent definition:** supplies `intent`, default `user_dims` (or merge rules), and default `mode` when opening a run.
- **Headers:** keep carrying `run_id` / parent span for hops; unchanged.

### Suggested direction

1. Dims/mode from agent setup (kwargs / `RunOpenOptions` / config), not scraped from `payload`.
2. Stop documenting UI-supplied `intent` / `mode` as the primary Chat / bench path.
3. Define precedence if payload still has keys (agent defaults win; allow-list client overrides like `user_id` only).
4. Update triad/brief entry servers + field guide.

### Acceptance sketch

- UI can `POST /v1/tasks` with only task content; entry still registers with stable `intent`/`mode` from agent config.
- Docs/examples no longer teach “put intent/mode in the UI payload” as the primary path.

---

## 2. Standardize policy names

**Area:** `src/tokenops/control/policies/*`, config YAML, Admin UI, docs

### Problem

Policy identifiers / display names are inconsistent across code, YAML, and docs (harder to learn, wire, and compare).

### Desired behavior

- One canonical name per policy (code module, YAML key, UI label mapping, docs slug).
- Document the naming convention (e.g. snake_case detector id = config key).
- Rename/alias plan for any legacy names so demos and seeded `default.yaml` stay coherent.

### Acceptance sketch

- Single glossary of policy ids; no duplicate aliases without an explicit deprecation path.

---

## 3. Scope policies to intent (where value-add lives)

**Area:** governance config, `Store.governance_config_for`, policy binding

### Problem

Unclear / insufficient today whether policies are (or can be) scoped by **intent**. Intent is where product value concentrates: different jobs need different caps and behaviors. If policies are only global or per-agent, we miss the main lever.

### Desired behavior

- Policies (and/or budgets) bindable by **intent** (alone or with agent), not only agent-wide defaults.
- Registration always carries a stable intent from the agent definition (see §1) so scoping is reliable.
- Admin / config UX makes intent-scoped rules first-class.

### Open question

- Confirm current behavior: what does `governance_config_for(agent)` actually filter on today? Extend to `(agent, intent)` or intent-first overlays.

### Acceptance sketch

- Same agent, two intents → different policy sets / budgets without forking agent code.
- Docs show intent-scoped config as the recommended model.

---

## 4. Remove inlining / embedding of the plane altogether

**Area:** `ControlPlaneClient.from_env`, `TOKENOPS_EMBEDDED`, local `Store` as plane substitute, `should_mount_run_registration`

### Problem

Embedded / in-process plane (`TOKENOPS_EMBEDDED`, no `TOKENOPS_URL`, mounting `/v1/runs` on the agent) duplicates control-plane responsibility inside agent processes. Two modes to explain, test, and keep in sync.

### Desired behavior

- Always talk to a real control plane over its API (`TOKENOPS_URL`).
- No embedded Store-as-plane path for product/demos; tests use a plane fixture or test server, not a second mental model.
- Agents never mount `/v1/runs`.

### Acceptance sketch

- `TOKENOPS_EMBEDDED` removed (or test-only and undocumented).
- One deployment story: plane process + agents with URL + shared contract via APIs.

---

## 5. Single run context manager (collapse entry vs downstream)

**Area:** `entry_task_run_scope`, `downstream_run_scope`, Chronicle overlap

### Problem

Split helpers (`entry_task_run_scope` vs `downstream_run_scope`) encode role in the API even though the same service can be entry or downstream per request. `entry_task_run_scope` already joins when `run_id` is present. Users should not choose between two scopes.

### Desired behavior

- **One** context manager for “this agent hop is under a governed run.”
- Internally: register if no `run_id`, else join; open span; bind context.
- Naming candidates (decide after Chronicle check):
  - `agentplane_run_scope` — TokenOps/AgentPlane-owned
  - `chronicled_run` / Chronicle-shaped name — **only if Chronicle already owns this concept**; do not fork vocabulary
- Remove public `downstream_run_scope` (and ideally `entry_task_run_scope`) from the integration surface.

### Open question

- Does Chronicle already provide a run/session scope we should wrap or extend instead of inventing `agentplane_run_scope`?

### Acceptance sketch

- Examples use a single `with <run_scope>(...):` in every agent handler.
- Field guide no longer teaches entry vs downstream scope helpers.

---

## 6. Do not pass a DB `Store` into the context manager — plane APIs only

**Area:** `Store` constructor on `TOKENOPS_DB`, scope helpers taking `store=`

### Problem

Agents construct `Store("tokenops.db")` and pass it into run scopes. That leaks persistence into the integration API and encourages treating the agent as a co-owner of the ledger DB.

### Desired behavior

- Context manager / SDK talks to the **control plane via APIs** (register, resolve run, fetch governance config, record spend / observe — as appropriate).
- SQLite (or any backend) stays **behind the plane**; agents do not open the DB file for governance.
- Aligns with §4 (no inlined plane).

### Acceptance sketch

- No `Store(path)` in example agent servers for governance.
- Integration code depends on `ControlPlaneClient` (or successor), not on SQLite schema.

---

## 7. Derive run context from request context — minimize agent diffs

**Area:** A2A/FastAPI (and other) request binding; scope manager ergonomics

### Problem

Handlers must manually thread `store`, `headers`, `payload` into the scope. That is noisy and forces large diffs in existing agents.

### Desired behavior

- Prefer ambient **request context** (framework middleware / Chronicle / ASGI contextvars): headers, body subset, service id already bound.
- Ideal shape roughly:

  ```python
  with agentplane_run_scope():  # or chronicled_run()
      ...
  ```

  with agent-definition defaults (intent/mode) from config, not per-call arguments.
- Optional explicit overrides for tests; production path is nearly zero boilerplate.
- Middleware (or one-liner install) extracts what TokenOps needs from the incoming request.

### Acceptance sketch

- Migrating an existing FastAPI/A2A agent is: install hook + one `with` (or decorator), not re-plumbing store/headers/payload through every handler.
- Document the minimal patch for a vanilla agent.

---

## Non-goals (for this note set)

- Rewriting agent business logic / prompts.
- Changing the idea of shared `run_id` + ledger across hops (still required).
- Building a new agent framework.

## Suggested implementation order

1. §4 + §6 — plane-only, API client (unblocks cleaner scope API)
2. §5 + §7 — single ambient scope manager
3. §1 — agent-defined intent/dims/mode
4. §3 — intent-scoped policies (depends on stable intent)
5. §2 — policy name standardization (can parallelize earlier)
