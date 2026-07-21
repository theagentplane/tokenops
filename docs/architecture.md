# TokenOps control plane — architecture & dependency graph

Where the code starts, how the modules depend on each other, and what each is for.
Control plane under `src/tokenops/control/`; SDK + plane; A2A demos and Chat/Simulator live in tokenops-wiki; state shared via one SQLite file.

---

## Starting points (what you call)

| Entry point | Module | Purpose |
|-------------|--------|---------|
| `POST /v1/runs` | `control/http.py` `mount_run_registration` (plane app) | register run dims |
| `ControlPlaneClient` | `control/client.py` | SDK register_run (HTTP or embedded Store) |
| `python -m tokenops.server` | `server/app.py` | standalone control plane (:7700) |
| `POST /v1/tasks` | `examples/a2a/server.py` ([tokenops-wiki](https://github.com/theagentplane/tokenops-wiki)) | task requires `X-TokenOps-Run-Id` |
| `build_attribution(reg, service=…)` | `attribution.py` | registration → ledger `Attribution` |
| `@boundary` + crossing hook | Chronicle + `control/crossing.py` | record crossing + govern ingest |
| `wrap_complete(…)` | `integration.py` | provider wrap — **pre_call** before dispatch |
| `build_governor(config, price)` | `config.py` | `budgets:`/`policies:` → wired `Governor` |
| `Store.governance_config_for(agent)` | `store.py` | SQLite → exact `build_governor` dict |
| `seed_default_governance_if_empty()` | `store.py` | first-open seed from `default.yaml` `governance:` |
| `run_simulation(…)` | `examples/ui/simulator.py` (wiki) | in-process research→summarize with trace log |

Native A2A servers (wiki) wire these per request; Admin writes the store; Dashboard reads runs.

## Dependency + data-flow graph

```mermaid
graph TD
    subgraph dataplane["data plane (your agents / wiki demos)"]
        agent["A2A / in-process agents"]
        chronicle["chronicle @boundary"]
    end

    subgraph uis["Product UI"]
        admin["Admin"]
        dash["Dashboard"]
    end

    store[("SQLite tokenops.db\nregistrations · budgets · policies · runs")]

    subgraph control["control plane"]
        attr["attribution · context"]
        boundary["boundary · integration"]
        cfg["config.build_governor"]
        engine["engine.Governor"]
        policies["policies/* (10)"]
        ledger["ledger + pricing"]
        plane["tokenops.server :7700"]
    end

    plane -->|register_run| store
    agent -->|TOKENOPS_URL / Store| plane
    admin -->|upsert| store
    store -->|governance_config_for| cfg
    agent -->|write RunRecord| store
    store -->|list_runs| dash
    chronicle --> boundary
    boundary --> engine
    agent --> boundary
    agent -->|wrap_complete| boundary
    cfg --> engine
    engine --> ledger
    policies --> ledger
```

## Runtime flow of one governed run

```
POST /v1/runs  { intent, user_dims }  →  run_registrations
POST /v1/tasks  +  X-TokenOps-Run-Id
  ├─ downstream_run_scope / entry_run_scope  →  SpanContext + registration in contextvars
  ├─ governor = build_governor(store.governance_config_for(agent), price, ApplyControls())
  ├─ store.create_run(RunRecord status="running")
  │
  ├─ agent.run(…, complete_fn=wrap_complete(…))
  │     pre_call  → worst-case / concurrency detectors
  │     dispatch  → providers.complete
  │     observe   → LLM Observation (via emit_observation in wrap)
  │     @boundary tool  → Chronicle envelope + observe
  │
  ├─ delegate  →  child server (same run_id, X-TokenOps-Parent-Span-Id)
  │     child spend → shared ledger (no parent rollup)
  │
  └─ store.update_run(status, halt_reason, cost_micros, steps)
```

The **Ledger** splits state by lifetime:

| State | Scope | Backend |
|---|---|---|
| Spend, inflight, halt | Cross-process (same `run_id`) | SQLite `ledger_*` tables in `tokenops.db` |
| Step window, local step count | Per agent process | In-memory `RunState` |

SQLite also holds config + run history. Pass `store=` into `build_governor(...)` so A2A servers share accumulators.

## DB maintenance

```bash
make db-clear    # wipe all rows
make db-reseed   # replace governance from default.yaml
make db-reset    # clear + reseed
```

Scripts: `scripts/db_clear.py`, `scripts/db_reseed.py`. UI `get_store()` uses `auto_seed=False`
(governance seeded at deploy or via scripts; Admin owns edits).

## Design rules

- Dependencies point **one way**; the data plane never imports control internals except taps.
- **Store assembles the `build_governor` dict** — YAML `governance:` is reference + auto-seed source.
- **Per-request governor** — concurrent runs never share window/halt/spend state.
- **Fail closed** — missing registration, unknown template, unknown price → refuse.

See also `docs/run-attribution.md`.
