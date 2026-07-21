# Code Navigation

How to find your way around TokenOps (core) and the two-agent bench.

## Layout

| Tree | Role |
|------|------|
| `src/tokenops/` | Reusable control plane (ledger, policies, Admin/Dashboard UI, providers, config) |
| `bench/` | Two-agent A2A test bench (agents, a2a protocol, chat + simulator UI, demo-assets) |

## Entry points

| Command | Start reading at |
|---------|------------------|
| `make research-server` | `bench/servers/research.py` → `bench/agents/research/{native,langchain}/server.py` |
| `make summarize-server` | `bench/servers/summarize.py` → `bench/agents/summarize/{native,langchain}/server.py` |
| `make ui` | `bench/ui/app.py` (chat + simulator + core Admin/Dashboard) |
| `make run` | `run.py` (agents + UI; frees ports first) |
| `make db-reset` | `scripts/db_clear.py` + `scripts/db_reseed.py` |

## Trace a governed run (native path)

```text
POST /v1/runs  →  control/http.py  (mount_run_registration; intent + user_dims)
POST /v1/tasks + X-TokenOps-Run-Id
  → bench/agents/research/native/server.py
  → store.governance_config_for → build_governor(..., store=store)
  → run_scope + governance_scope
  → bench/agents/research/native/agent.py
      → wrap_complete (pre_call + observe on LLM)
      → @boundary search (Chronicle + crossing hook → observe)
  → bench/a2a/client.py delegate_summarize (parent span header)
      → bench/agents/summarize/native/server.py (downstream_run_scope)
  → store.update_run → Dashboard
```

## Trace a simulator run (in-process)

```text
bench/ui/views/simulator_view.py
  → bench/ui/simulator.py run_simulation()
    → register_run + TraceGovernor (store-backed ledger)
    → research agent → summarize agent (same process)
    → events + chronicle envelopes + ledger windows
```

## Streamlit pages

| Page | File |
|------|------|
| Test Bench | `bench/ui/views/chat.py` |
| Run simulator | `bench/ui/views/simulator_view.py` |
| Policy admin | `src/tokenops/ui/views/admin.py` |
| Dashboard | `src/tokenops/ui/views/dashboard.py` |
| Bench entry | `bench/ui/app.py` |
| Product-only entry | `src/tokenops/ui/app.py` |

## Layer cake (onboarding read order)

1. `docs/run-attribution.md`, `control/context.py`, `control/attribution.py`
2. `bench/agents/types.py`, `config/schema.py`
3. Chronicle `@boundary` + `control/crossing.py` + `control/boundary.py` + `control/integration.py`
4. `control/ledger.py` (hybrid local + SQLite), `control/engine.py`, `control/policies/`
5. `control/store.py`, `ui/views/admin.py`
6. `bench/a2a/server.py`, `control/http.py`, `bench/agents/*/native/server.py`
7. `bench/ui/simulator.py`, `bench/ui/views/simulator_view.py`

## Framework fork

Only `bench/agents/factory.py` and `{native,langchain}/` folders differ by framework. Prompts, tool core, providers, and A2A layer are shared.

## Quick lookup

| Change… | Open… |
|---------|--------|
| UI / Test Bench | `bench/ui/app.py`, `bench/ui/views/chat.py` |
| Run simulator | `bench/ui/simulator.py`, `bench/ui/views/simulator_view.py` |
| Shared-ledger demo | `scripts/prep_ledger_comparison.py`, `docs/shared-ledger-comparison.md` |
| Policy admin | `tokenops/ui/views/admin.py`, `control/store.py` |
| Dashboard | `tokenops/ui/views/dashboard.py` |
| Crossing hook | `control/crossing.py` |
| Run registration | `control/http.py`, `control/attribution.py` |
| DB reset scripts | `scripts/db_clear.py`, `scripts/db_reseed.py`, `Makefile` |
| Config / presets | `config/schema.py`, `config/presets/` |
| A→B delegation | `bench/a2a/client.py`, `research/*/server.py` |
| A2A payloads | `bench/a2a/messages.py` |
| Search / corpus | `bench/agents/research/tools/core.py` |
| Model APIs | `providers/` |
