# Code Navigation

How to find your way around the test bench codebase.

## Entry points

| Command | Start reading at |
|---------|------------------|
| `make research-server` | `src/tokenops/servers/research.py` → `agents/research/{native,langchain}/server.py` |
| `make summarize-server` | `src/tokenops/servers/summarize.py` → `agents/summarize/{native,langchain}/server.py` |
| `make ui` | `src/tokenops/ui/app.py` |
| `make run` | `run.py` (agents + UI; frees ports first) |
| `make db-reset` | `scripts/db_clear.py` + `scripts/db_reseed.py` |

## Trace a governed run (native path)

```text
POST /v1/runs  →  a2a/server.py  (register intent + user_dims)
POST /v1/tasks + X-TokenOps-Run-Id
  → agents/research/native/server.py
    → store.governance_config_for → build_governor(..., store=store)
    → run_scope + governance_scope
    → agents/research/native/agent.py
      → wrap_complete (pre_call + observe on LLM)
      → @boundary search (chronicle + observe)
    → a2a/client.py delegate_summarize (parent span header)
      → agents/summarize/native/server.py (downstream_run_scope)
  → store.update_run → Dashboard
```

## Trace a simulator run (in-process)

```text
ui/pages/3_Simulator.py
  → ui/simulator.py run_simulation()
    → register_run + TraceGovernor (store-backed ledger)
    → research agent → summarize agent (same process)
    → events + chronicle envelopes + ledger windows
```

## Streamlit pages

| Page | File |
|------|------|
| Test Bench | `ui/app.py` |
| Policy admin | `ui/pages/1_Admin.py` |
| Dashboard | `ui/pages/2_Dashboard.py` |
| Run simulator | `ui/pages/3_Simulator.py` |

## Layer cake (onboarding read order)

1. `docs/run-attribution.md`, `control/context.py`, `control/attribution.py`
2. `agents/types.py`, `config/schema.py`
3. `chronicle/boundary.py`, `control/boundary.py`, `control/integration.py`
4. `control/ledger.py` (hybrid local + SQLite), `control/engine.py`, `control/policies/`
5. `control/store.py`, `ui/pages/1_Admin.py`
6. `a2a/server.py`, `agents/*/native/server.py`
7. `ui/simulator.py`, `ui/pages/3_Simulator.py`

## Framework fork

Only `agents/factory.py` and `{native,langchain}/` folders differ by framework. Prompts, tool core, providers, and A2A layer are shared.

## Quick lookup

| Change… | Open… |
|---------|--------|
| UI / Test Bench | `ui/app.py` |
| Run simulator | `ui/simulator.py`, `ui/pages/3_Simulator.py` |
| Shared-ledger demo | `scripts/prep_ledger_comparison.py`, `docs/shared-ledger-comparison.md` |
| Policy admin | `ui/pages/1_Admin.py`, `control/store.py` |
| Dashboard | `ui/pages/2_Dashboard.py` |
| Run registration | `a2a/server.py`, `control/attribution.py` |
| DB reset scripts | `scripts/db_clear.py`, `scripts/db_reseed.py`, `Makefile` |
| Config / presets | `config/schema.py`, `config/presets/` |
| A→B delegation | `a2a/client.py`, `research/*/server.py` |
| A2A payloads | `a2a/messages.py` |
| Search / corpus | `agents/research/tools/core.py` |
| Model APIs | `providers/` |
