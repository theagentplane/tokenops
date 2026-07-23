# Design fix notes (TokenOps integration surface)

**Status:** Wave 1–2 done (legacy public scopes removed)  
**Date:** 2026-07-23  
**Context:** Captured during beginner walkthrough; product/API direction.

**Wave 1–2 (implemented):** `tokenops.init` / `ControlPlaneClient.from_env` /
`instrument_app`; unified `tokenops_run` (+ `agentplane_run_scope`);
`RequestContext`; agent-owned `intent`/`mode`/`user_dims`. Public
`entry_task_run_scope` / `downstream_run_scope` / `entry_run_scope` /
`governance_scope` / `build_attribution` **removed** — happy path is
`instrument_app` + `tokenops_run` only.

**Deferred (other waves):** §6 plane-only Store, §11 governor container, §16 parallel detectors, etc.

**Wave 3 (in tree):** §15 thread safety — Store/Ledger RLock, governance cache contract, `docs/concurrency.md`, `tests/test_thread_safety.py`.

---

## 1. Run registration dims from agent definition, not UI

**Status:** done — agent kwargs / `instrument_app` win; UI sends task only.

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

**Status:** done — public API is `tokenops_run` only; legacy scopes deleted.

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

## 8. Minify UX — leaky abstractions must not be forced

**Status:** done — field guide / README / skill teach `instrument_app` + `tokenops_run` only.

**Area:** integration surface (`build_attribution`, scopes, `Store`, `governance_scope`, field guide)

**Principle:** Control is available; control is not forced. Defaults first; advanced escape hatches opt-in.

### Problem

Integrators are required to wire low-level control-plane concepts that TokenOps already has enough context to derive. That leaks internal types into every agent handler and inflates the “minimal” integration path.

Forced today (non-exhaustive):

| Leaky call / concept | Why the user shouldn’t have to |
|----------------------|--------------------------------|
| `build_attribution(reg, service=...)` | Registration + service already known; build inside ambient scope |
| Pass `store`, `headers`, `payload` into every scope | Derive from request context / middleware (§7) |
| Choose `entry_task_run_scope` vs `downstream_run_scope` | One run scope; role is per-request (§5) |
| Construct `Store(TOKENOPS_DB)` in the agent | Plane APIs only (§4, §6) |
| Hand-roll `build_governor` + `governance_scope` + `attr` every handler | Collapse behind install + one `with` / decorator |
| UI must supply `intent` / `mode` on task JSON | Agent definition owns defaults (§1) |

### Desired behavior

| Default (min friction) | Advanced (opt-in) |
|------------------------|-------------------|
| Middleware / single scope binds run + governance + attribution | Explicit `Attribution`, custom dims, preview mode, overrides |
| Plane client from env; no SQLite in agent | Custom client / test doubles |
| Agent config supplies intent/mode | Per-request overrides where allow-listed |

### Acceptance sketch

- Field-guide “minimal patch” for a vanilla agent does **not** mention `build_attribution`, `Store(path)`, or choosing entry vs downstream scope.
- Example servers use the minimal path; advanced examples may still show overrides.
- Docs state the principle: defaults first, control optional.

### Tracking

In-repo only (no GitHub issue for this batch). Closely related to §1, §5, §6, §7 — treat this section as the **UX north star** for those API changes.

---

## 9. Unify run scope + governance scope

**Status:** done — `tokenops_run` binds both; `_governance_scope` is private.

**Area:** `entry_*/downstream_run_scope`, `governance_scope`, registration `mode`

### Problem

Two nested context managers for one hop. Registration already carries **mode** (enforce vs preview). Splitting “which run” from “which governor” forces boilerplate and contradicts §8.

### Desired behavior

- **One** ambient scope opens the run *and* binds governance (governor, attribution, provider/model defaults).
- Mode on the run (or agent config) selects `ApplyControls` vs `PreviewControls` internally.
- Advanced users may still pass an explicit governor / mode override.

### Acceptance sketch

- Examples: single `with …_run_scope():` (or successor name); no separate `governance_scope` on the happy path.

---

## 10. Governor construction: config from env, clone per run

**Area:** `build_governor`, `governance_config_for`, agent startup

### Problem

Handlers call `store.governance_config_for(agent)` and `build_governor(...)` on every request — DB/config load + template wiring repeated; also forces Store into the handler (§6, §8).

### Desired behavior

- On TokenOps / agent **init**: load governance config once (env / plane API / agent config file).
- Build a **prototype Governor** (templates + budgets wired).
- **Clone** (or cheap copy) per run/request so in-memory window / controls stay isolated — without re-reading config from DB every time.
- Manual `build_governor(config=...)` remains for tests and advanced override.

### Acceptance sketch

- Hot path does not call `governance_config_for` per task.
- Config refresh is explicit (SIGHUP / admin push / TTL), not implicit per request.

---

## 11. `GovernorContainer` — process-global, keyed by `run_id`

**Area:** Governor lifecycle, concurrency, cleanup

### Problem

Today: new Governor per handler call. Shared spend already lives in SQLite; request-local Governors avoid shared in-memory windows but push construction onto the user and duplicate wiring.

### Desired behavior

- Top-level **`GovernorContainer`** (name TBD) is process-global / singleton-friendly.
- Internally holds **per-`run_id` Governor** (or run state) instances.
- `pre_call` / `observe` route by `run_id` from ambient attribution.
- **Periodic cleanup** of completed / halted / TTL-expired runs’ local state.
- Cloning from prototype (§10) when a run is first seen.

### Open questions

- Cleanup triggers: run terminal status from plane, idle TTL, max entries.
- Multi-worker processes: container is per process; ledger remains shared via plane — document that.

### Acceptance sketch

- Agent code does not `build_governor` per request; it talks to the container (or ambient scope does).
- Concurrent runs in one process do not share step windows.

---

## 12. Cross-platform LLM wrap (OAI, GHCP SDK, LangChain, …)

**Area:** `wrap_complete`, `GovernedChatModel`, provider adapters

### Problem

`wrap_complete` assumes a TokenOps-shaped `complete(provider, model, messages, **kwargs)`. Real stacks construct the “model node” differently (OpenAI client, GitHub Copilot SDK, LangChain `BaseChatModel`, etc.). Brief’s `GovernedChatModel` is one ad-hoc bridge — not a general story.

### Desired behavior

- Thin **adapter interface**: normalize messages in/out + usage; plug into one governance wrap.
- Official adapters (or recipes) for: raw OpenAI, LangChain chat model, and other common SDKs (incl. GHCP when relevant).
- Prefer “inject governed node” over rewriting agent graphs.
- Align with Chronicle owning the LLM boundary (§17) so one instrumentation story serves trace + govern.

### Acceptance sketch

- Same governance semantics across adapters; field guide shows ≥2 platforms without custom forks of `wrap_complete`.

---

## 13. Better output-token prediction

**Area:** `pre_call_worst_case`, `CallRequest.max_output_tokens`, `est_input`

### Problem

Worst-case gating depends on `max_output` / defaults (e.g. 1024). Uncapped calls MUTATE to a default; projection is coarse. Bad estimates → false HALTs or weak prevention.

### Desired behavior

- Better estimators: task/intent priors, model context window, historical p50/p95 for this agent+intent, optional caller hint.
- Keep fail-closed on unknown price; never price physical model max without a bound.
- Document accuracy limits; prefer MUTATE-to-priced-cap over crude HALT when headroom exists.

### Acceptance sketch

- Measurable reduction in false-positive pre_call HALTs on demo workloads without raising overspend rate.

---

## 14. Policy execution audit trail (logging + action provenance)

**Area:** `Governor._enforce`, `ApplyControls.event_log`, `governance_events_payload`

### Current behavior (as of note date)

- Detectors/policies: **no** structured per-policy execution logs inside `Governor`.
- Actions appended to `controls.event_log`; persisted via `governance_events_payload` as `{kind, reason, policy?}` where **policy is inferred from `reason` text** (`policy_hint_from_reason`), not a first-class field on `Action`.
- **Ledger snapshot at decision time is not recorded** on the action (spent, left, step_count, evidence may live on `Signal` but is not systematically persisted with the applied action).

### Desired behavior

- Every applied action records: **policy/detector name**, severity, action kind, reason, **signal evidence**, and a **ledger snapshot** (e.g. `cost_micros`, `budget_left`, `step_count`, halt flag).
- Optional debug logs per detect → decide → apply (level-gated).
- Dashboard / run record can answer: “who tripped, why, what did the books look like?”

### Acceptance sketch

- `Action` (or event row) carries `detector` / `policy` explicitly; no regex-on-reason.
- Halted runs show ledger snapshot at HALT in Admin/Dashboard.

---

## 15. Thread safety

**Area:** `Ledger`, `Store` (SQLite `check_same_thread=False`), `Governor` / container, contextvars

### Current behavior (as of note date)

- SQLite opened with `check_same_thread=False`; **no** documented locking protocol for concurrent writers.
- In-memory ledger maps / step windows are not clearly mutex-protected.
- Mitigation today: **per-request Governor** + contextvars (task/request local), shared spend via SQLite — concurrency safety is **assumed by isolation**, not proven for a shared Governor.
- Trajectory drain uses a thread + lock; that is local to that feature.

### Desired behavior

- Explicit concurrency model: safe concurrent `pre_call`/`observe` for **different** `run_id`s on `GovernorContainer`; defined behavior for same `run_id` re-entrancy.
- Plane/DB access serialized or transactional; document multi-process + multi-thread guarantees.
- Tests: concurrent runs in one process; no lost updates / torn halt flags.

### Acceptance sketch

- Written concurrency contract in docs; tests covering container + shared ledger under threads/async tasks.

---

## 16. Parallel detectors; highest severity wins / short-circuit

**Area:** `Governor.pre_call` / `observe` / `_enforce`

### Current behavior

- Detectors run **sequentially**; all signals collected; then sorted by severity (TRIP > WARN > OK) and enforced in order.

### Desired behavior

- Run detectors **in parallel** (thread/async pool as appropriate).
- **First highest-severity** outcome can **cancel/ignore the rest** (short-circuit): e.g. any TRIP wins and remaining detector work is aborted when practical.
- Preserve deterministic tie-break (policy priority / name order) when severities equal.
- Keep unit tests deterministic (fake executor or ordered barrier in tests).

### Acceptance sketch

- Semantics documented; TRIP from one detector does not wait on slow detectors unnecessarily.
- No flaky tests from scheduling.

---

## 17. Auto `install_crossing_hook` on TokenOps init

**Area:** `install_crossing_hook`, package/agent bootstrap

### Problem

Users must remember `install_crossing_hook()` once per process — easy to forget; violates §8.

### Desired behavior

- Calling TokenOps init / creating the client / first ambient scope **installs the crossing hook** (idempotent).
- Manual install remains available; not required on the happy path.

### Acceptance sketch

- Field guide omits a standalone “don’t forget the hook” step for default setup.

---

## 18. Chronicle owns LLM tracing; TokenOps only bridges crossings

**Area:** Chronicle `@boundary`, `wrap_complete`, crossing hook

### Current behavior

- Chronicle traces via `@boundary` (tools in demos; LLM if you decorate `kind="llm"`).
- TokenOps **`wrap_complete`** governs LLMs and emits Observations **directly** — often **bypassing Chronicle**, so Chronicle is not the full tracer for LLM calls in TokenOps benches.

### Desired behavior

- **Chronicle** provides the full tracing suite: tools + LLM (+ other kinds) with one pattern (`@boundary` or equivalent object/adapter wrap for non-function model nodes — see §12).
- **TokenOps** only **subscribes** via crossing hook (same as tools): crossing → Observation → Governor.
- Governance wrap (pre_call MUTATE/HALT before dispatch) may still sit adjacent, but **recording/trace** of the LLM call should flow through Chronicle so traces are complete and one mental model applies.
- Move or dual-publish LLM instrumentation so Chronicle has the “full suite”; TokenOps does not fork a second tracer.

### Open questions

- Where does **pre_call** live if Chronicle records after/around the call? (TokenOps may keep a thin pre-dispatch gate; Chronicle still records the crossing.)
- Object-style model nodes: Chronicle needs the same adapter story as §12.

### Acceptance sketch

- Demo LLM calls appear in Chronicle traces/envelopes by default.
- TokenOps ledger ingest for LLM uses the same `on_crossing` path as tools.
- Docs: Chronicle = tracer; TokenOps = governor on crossings.

---

## Non-goals (for this note set)

- Rewriting agent business logic / prompts.
- Changing the idea of shared `run_id` + ledger across hops (still required).
- Building a new agent framework.
- Filing GitHub issues for this batch (notes file is the backlog).

## Suggested implementation order

1. §4 + §6 — plane-only, API client (unblocks cleaner scope API)
2. §10 + §11 — prototype governor + `GovernorContainer` (enables safer global lifecycle)
3. §5 + §7 + §8 + §9 + §17 — single ambient scope, minify UX, auto crossing hook
4. §18 + §12 — Chronicle-owned LLM trace + cross-platform adapters
5. §1 + §3 — agent-defined intent + intent-scoped policies
6. §14 + §15 + §16 — audit trail, thread safety, parallel detectors
7. §13 — better output-token prediction
8. §2 — policy name standardization (can parallelize earlier)

## Quick answers (snapshot at note time)

| Question | Today |
|----------|--------|
| Logs per policy execution in Governor? | **No** structured per-detect/decide logs |
| Action records policy + ledger state? | **Partial** — `event_log` + reason; policy often inferred from reason; **no** ledger snapshot on action |
| Thread safe? | **Not a hard guarantee** — isolation via per-request Governor + SQLite; needs §15 |
| Detectors parallel? | **No** — sequential collect, then severity sort |
| Chronicle trace LLM by default in TokenOps demos? | **Usually no** — `wrap_complete` path; tools use `@boundary` |
