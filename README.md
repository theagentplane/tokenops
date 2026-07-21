# TokenOps Test Bench

[![Type Checking](https://img.shields.io/badge/types-Mypy%20%7C%20Strict-2A2A2A?style=flat-square)](https://mypy-lang.org/)
[![Telemetry Standard](https://img.shields.io/badge/telemetry-OpenTelemetry%20GenAI-334155?style=flat-square&logo=opentelemetry)](https://opentelemetry.io/)
[![Status](https://img.shields.io/badge/status-0.x%20%7C%20draft-7B61FF?style=flat-square)](https://semver.org/)

A two-agent research pipeline test bench. **Research** (Agent A) runs a search loop, then delegates findings to **Summarize** (Agent B) over A2A-style HTTP. Agents run as separate processes with swappable **native** or **LangChain** implementations.

## Quick start

```bash
make install
cp .env.example .env   # add your API keys (optional for simulator demo mode)

make db-reset          # optional: clean SQLite + seed governance from default.yaml
make run               # control plane :7700 + agents + UI (Ctrl+C stops all; frees stale ports)
```

**Docker (same shape as cloud):** plane + research + summarize sharing a DB volume —

```bash
docker compose up --build
# optional UI: docker compose --profile ui up --build
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

# Terminal 4
make ui
```

Open http://localhost:8501.

| Page | Purpose |
|------|---------|
| **Test Bench** | Live A2A pipeline (research → summarize) |
| **Run simulator** | In-process run with trace, spans, control-plane timeline (demo mode = no API key) |
| **Policy admin** | Edit budgets, policies, segments (SQLite) |
| **Dashboard** | Run history, cost, halt reasons |

Configure agents in the Test Bench sidebar, or use **Run simulator** for governance debugging.

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

Research uses **DuckDuckGo** by default ([`ddgs`](https://pypi.org/project/ddgs/) package) — free, no API key.

| Corpus profile | Behavior |
|----------------|----------|
| `healthy` | Real web snippets with heuristic completeness score |
| `leak` | Same results, garbled (truncation, masked prices, low completeness) |

## Configuration

Default config: [`src/tokenops/config/default.yaml`](src/tokenops/config/default.yaml)

Presets for all four framework combos: [`src/tokenops/config/presets/`](src/tokenops/config/presets/)

Set a custom config path:

```bash
export TOKENOPS_CONFIG=path/to/config.yaml
make research-server
```

## Architecture

```
src/tokenops/   # control plane SDK + standalone plane (server/) + Admin/Dashboard
bench/          # two-agent A2A test bench (agents, a2a, chat + simulator, demo-assets)
```

- UI / clients register runs on the **control plane** (`ControlPlaneClient` → `TOKENOPS_URL`)
- Research completes research, then calls summarize via A2A HTTP
- Summarize returns summary to research; research returns full result to UI

See [`docs/code-navigation.md`](docs/code-navigation.md) and [`docs/control-plane-deploy.md`](docs/control-plane-deploy.md).

## Documentation

- [Control plane status](CONTROL_PLANE.md)
- [Control plane deploy](docs/control-plane-deploy.md) — compose vs SDK, `TOKENOPS_URL`, `register_run`
- [Customer outcomes](docs/customer-outcomes.md) — first-order metrics: cost, completion under budget, quality
- [Run attribution](docs/run-attribution.md)
- [Architecture](docs/architecture.md)
- [Shared ledger comparison](docs/shared-ledger-comparison.md) — multi-agent run budget before/after
- [Why Token Governance?](docs/why-token-governance.md)
- [Agent Spec](docs/agent-spec.md)
- [Code Navigation](docs/code-navigation.md)
