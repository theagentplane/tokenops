# TokenOps

[![CI](https://github.com/theagentplane/tokenops/actions/workflows/test.yml/badge.svg)](https://github.com/theagentplane/tokenops/actions/workflows/test.yml)
[![Type Checking](https://img.shields.io/badge/types-Mypy%20%7C%20Strict-2A2A2A?style=flat-square)](https://mypy-lang.org/)
[![Telemetry Standard](https://img.shields.io/badge/telemetry-OpenTelemetry%20GenAI-334155?style=flat-square&logo=opentelemetry)](https://opentelemetry.io/)
[![Status](https://img.shields.io/badge/status-0.x%20%7C%20draft-7B61FF?style=flat-square)](https://semver.org/)

**Control plane + SDK** for run-aware agent token governance — plus in-repo A2A demos and benches.

| Piece | What |
|-------|------|
| **Control plane** | `make control-plane` → `POST /v1/runs` on `:7700`, shared `TOKENOPS_DB` |
| **SDK (in agents)** | `ControlPlaneClient`, `wrap_complete`, `governance_scope`, Chronicle crossing hook |
| **Product UI** | `make ui` — Admin + Dashboard |
| **Examples** | `make demo` / `demo-triad` / `demo-brief` — two-agent, triad, brief benches |

## Quick start

```bash
make install
cp .env.example .env   # optional API keys for demos / your agents

make db-reset          # optional: clean SQLite + seed governance from default.yaml
make run               # control plane :7700 + Admin/Dashboard (Ctrl+C stops)
```

Demos:

```bash
make demo              # plane + research/summarize + Admin UI
make demo-triad        # plane + planner/researcher/writer
make demo-brief        # plane + scout/analyst/editor (LangChain)
make bench-ui          # Chat + Simulator only
```

Or plane only:

```bash
make control-plane     # :7700
export TOKENOPS_URL=http://localhost:7700
make ui                # Admin + Dashboard :8501
```

Docker:

```bash
docker compose up --build
# optional UI: docker compose --profile ui up --build
# two-agent stack:
docker compose -f docker-compose.examples.yml up --build
```

See [`docs/control-plane-deploy.md`](docs/control-plane-deploy.md) and [`examples/README.md`](examples/README.md).

### Make targets

| Target | Role |
|--------|------|
| `make control-plane` | Standalone plane (`python -m tokenops.server`) |
| `make ui` | Admin + Dashboard |
| `make run` | Plane + Admin/Dashboard |
| `make demo` / `demo-triad` / `demo-brief` | Runnable A2A stacks |
| `make bench-ui` | Chat + Simulator |
| `make db-reset` | Clear SQLite + reseed from `TOKENOPS_CONFIG` |

## Install as a library

```bash
pip install "tokenops @ git+https://github.com/theagentplane/tokenops.git"
# or from a checkout:
pip install -e ".[dev,examples]"
```

```python
from tokenops import ControlPlaneClient
from tokenops.control import wrap_complete, entry_task_run_scope, install_crossing_hook
```

Integration skill: [`.cursor/skills/integrate-tokenops/SKILL.md`](.cursor/skills/integrate-tokenops/SKILL.md).
Field guide: [`docs/guides/field-guide-add-tokenops.md`](docs/guides/field-guide-add-tokenops.md).

## Architecture

```
src/tokenops/     # installable package (SDK, plane, Admin UI)
examples/         # A2A benches (two-agent, triad, brief) + Chat/Simulator
benchmarking/     # MetaGPT / browser-use live harness
docs/             # architecture, policies, guides, product
```

- Entry agents register runs via `ControlPlaneClient` → plane `POST /v1/runs`
- Agents share spend through `TOKENOPS_DB` when using the same `run_id`

## Documentation

- [Control plane status](CONTROL_PLANE.md)
- [Control plane deploy](docs/control-plane-deploy.md)
- [Run attribution](docs/run-attribution.md)
- [Architecture](docs/architecture.md)
- [Examples](examples/README.md)
- [Field guide](docs/guides/field-guide-add-tokenops.md)
- [Code Navigation](docs/code-navigation.md)
- [Testing](docs/testing.md)
- [Product: comparison](docs/product/comparison.md) · [shared ledger](docs/product/shared-ledger.md) · [demo bench](docs/product/demo-bench.md)
