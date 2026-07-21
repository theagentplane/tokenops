# TokenOps Test Bench

[![Type Checking](https://img.shields.io/badge/types-Mypy%20%7C%20Strict-2A2A2A?style=flat-square)](https://mypy-lang.org/)
[![Telemetry Standard](https://img.shields.io/badge/telemetry-OpenTelemetry%20GenAI-334155?style=flat-square&logo=opentelemetry)](https://opentelemetry.io/)
[![Status](https://img.shields.io/badge/status-0.x%20%7C%20draft-7B61FF?style=flat-square)](https://semver.org/)

A multi-agent A2A test bench for TokenOps. The default stack is the **two-agent** pipeline
(**Research** → **Summarize**). A **three-agent triad** (**Planner** → **Researcher** → **Writer**)
is also available for richer governance demos (shared run ledger, tool boundaries, delegate rollups).

## Quick start

```bash
make install
cp .env.example .env   # add your API keys (optional for simulator demo mode)

make db-reset          # optional: clean SQLite + seed governance from default.yaml
make run               # control plane :7700 + agents + Admin/Dashboard (Ctrl+C stops all; frees stale ports)
```

**Docker (same shape as cloud):** plane + research + summarize sharing a DB volume —

```bash
docker compose up --build
# optional product UI (Admin + Dashboard): docker compose --profile ui up --build
```

See [`docs/control-plane-deploy.md`](docs/control-plane-deploy.md).

Or run each process separately:

```bash
# Terminal 1 — control plane (POST /v1/runs)
make control-plane
export TOKENOPS_URL=http://localhost:7700

# Terminal 2
make research-server

# Terminal 3
make summarize-server

# Terminal 4 — plane product UI (Admin + Dashboard)
make ui

# Optional — bench Chat + Simulator demos
make bench-ui
```

Open http://localhost:8501.

| Page | Entry | Purpose |
|------|-------|---------|
| **Policy admin** | `make ui` / compose `--profile ui` | Edit budgets, policies, segments (SQLite) |
| **Dashboard** | same | Run history, cost, halt reasons |
| **Test Bench (Chat)** | `make bench-ui` only | Live A2A pipeline (research → summarize) |
| **Run simulator** | `make bench-ui` only | In-process run with trace, spans (demo mode = no API key) |

Configure agents in the Test Bench sidebar (`make bench-ui`), or use **Run simulator** for governance debugging.

### Triad bench (Planner → Researcher → Writer)

Three-process A2A stack with the same control plane / shared `TOKENOPS_DB`:

| Agent | Port | Seams |
|-------|------|--------|
| Planner (entry) | 8011 | `register_run` → `wrap_complete` → delegates |
| Researcher | 8012 | `wrap_complete` + `@boundary` tools + crossing hook |
| Writer | 8013 | `wrap_complete`; parent observes delegate rollup |

```bash
# Seed demo-friendly cost_budget / step_cap, then start plane + 3 agents + UI
TOKENOPS_CONFIG=src/tokenops/config/triad.yaml make db-reset
make run-triad

# Or process-by-process
make control-plane
export TOKENOPS_URL=http://localhost:7700 TOKENOPS_CONFIG=src/tokenops/config/triad.yaml
make writer-server      # :8013
make researcher-server  # :8012
make planner-server     # :8011
```

Docker overlay (does not replace the two-agent compose services):

```bash
docker compose -f docker-compose.yml -f docker-compose.triad.yml up --build tokenops planner researcher writer
```

Client:

```bash
export TOKENOPS_URL=http://localhost:7700
python -c "
from bench.triad import submit_goal_sync_with_meta
r, meta = submit_goal_sync_with_meta('http://localhost:8011', 'Explain mid-market CRM pricing')
print(meta)
"
```

Field guide (how TokenOps was added): [`docs/field-guide-add-tokenops.md`](docs/field-guide-add-tokenops.md).

### Governance / DB

- Config lives in **`tokenops.db`** (env `TOKENOPS_DB`), seeded from `default.yaml` `governance:` on first open.
- Control plane URL: **`TOKENOPS_URL`** (e.g. `http://localhost:7700`). Agents register via `ControlPlaneClient`; set `TOKENOPS_EMBEDDED=1` for in-process Store (tests).
- Edit budgets/policies in **Policy admin** — changes apply on the next run.
- Reset: `make db-reset` · see `CONTROL_PLANE.md`

API keys live in a **`.env`** file at the repo root (loaded by both agent servers). Copy `.env.example` to `.env` and set:

- `OPENAI_API_KEY` — if research (or any agent) uses OpenAI
- `ANTHROPIC_API_KEY` — if summarize (or any agent) uses Anthropic

You can still `export` keys in your shell; those override `.env`.

## Search tool

Research / triad Researcher use **DuckDuckGo** by default ([`ddgs`](https://pypi.org/project/ddgs/) package) — free, no API key.

| Corpus profile | Behavior |
|----------------|----------|
| `healthy` | Real web snippets with heuristic completeness score |
| `leak` | Same results, garbled (truncation, masked prices, low completeness) |

## Configuration

Default config: [`src/tokenops/config/default.yaml`](src/tokenops/config/default.yaml)

Triad config: [`src/tokenops/config/triad.yaml`](src/tokenops/config/triad.yaml)

Presets for all four framework combos: [`src/tokenops/config/presets/`](src/tokenops/config/presets/)

Set a custom config path:

```bash
export TOKENOPS_CONFIG=path/to/config.yaml
make research-server
```

## Architecture

```
src/tokenops/   # control plane SDK + standalone plane (server/) + Admin/Dashboard
bench/          # A2A test benches
  agents/       # two-agent research + summarize
  triad/        # three-agent planner + researcher + writer
  a2a/ ui/      # shared HTTP helpers + Chat/Simulator
```

- UI / clients register runs on the **control plane** (`ControlPlaneClient` → `TOKENOPS_URL`)
- Research completes research, then calls summarize via A2A HTTP
- Triad: Planner plans, delegates to Researcher, then Writer; same `run_id` + shared ledger

See [`docs/code-navigation.md`](docs/code-navigation.md) and [`docs/control-plane-deploy.md`](docs/control-plane-deploy.md).

## Documentation

- [Control plane status](CONTROL_PLANE.md)
- [Control plane deploy](docs/control-plane-deploy.md) — compose vs SDK, `TOKENOPS_URL`, `register_run`
- [Field guide: add TokenOps to the triad](docs/field-guide-add-tokenops.md)
- [Customer outcomes](docs/customer-outcomes.md) — first-order metrics: cost, completion under budget, quality
- [Run attribution](docs/run-attribution.md)
- [Architecture](docs/architecture.md)
- [Shared ledger comparison](docs/shared-ledger-comparison.md) — multi-agent run budget before/after
- [Why Token Governance?](docs/why-token-governance.md)
- [Agent Spec](docs/agent-spec.md)
- [Code Navigation](docs/code-navigation.md)
