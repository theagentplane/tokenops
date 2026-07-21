# TokenOps

[![CI](https://github.com/theagentplane/tokenops/actions/workflows/test.yml/badge.svg)](https://github.com/theagentplane/tokenops/actions/workflows/test.yml)
[![Type Checking](https://img.shields.io/badge/types-Mypy%20%7C%20Strict-2A2A2A?style=flat-square)](https://mypy-lang.org/)
[![Telemetry Standard](https://img.shields.io/badge/telemetry-OpenTelemetry%20GenAI-334155?style=flat-square&logo=opentelemetry)](https://opentelemetry.io/)
[![Status](https://img.shields.io/badge/status-0.x%20%7C%20draft-7B61FF?style=flat-square)](https://semver.org/)

**Control plane + SDK** for run-aware agent token governance.

| Piece | What |
|-------|------|
| **Control plane** | `make control-plane` → `POST /v1/runs` on `:7700`, shared `TOKENOPS_DB` |
| **SDK (in agents)** | `ControlPlaneClient`, `wrap_complete`, `governance_scope`, Chronicle crossing hook |
| **Product UI** | `make ui` — Admin + Dashboard |

Runnable A2A demos (two-agent, triad, Chat/Simulator, benchmarking) live in
[**tokenops-wiki**](https://github.com/theagentplane/tokenops-wiki).

## Quick start

```bash
make install
cp .env.example .env   # optional API keys for your own agents

make db-reset          # optional: clean SQLite + seed governance from default.yaml
make run               # control plane :7700 + Admin/Dashboard (Ctrl+C stops)
```

Or separately:

```bash
make control-plane     # :7700
export TOKENOPS_URL=http://localhost:7700
make ui                # Admin + Dashboard :8501
```

Docker:

```bash
docker compose up --build
# optional UI: docker compose --profile ui up --build
```

See [`docs/control-plane-deploy.md`](docs/control-plane-deploy.md).

### Make targets

| Target | Role |
|--------|------|
| `make control-plane` | Standalone plane (`python -m tokenops.server`) |
| `make ui` | Admin + Dashboard |
| `make run` | Plane + Admin/Dashboard |
| `make db-reset` | Clear SQLite + reseed from `TOKENOPS_CONFIG` |

## Install as a library

```bash
pip install "tokenops @ git+https://github.com/theagentplane/tokenops.git"
```

```python
from tokenops import ControlPlaneClient
from tokenops.control import wrap_complete, entry_task_run_scope, install_crossing_hook
```

Integration skill: [`.cursor/skills/integrate-tokenops/SKILL.md`](.cursor/skills/integrate-tokenops/SKILL.md).
Examples / field guide: [tokenops-wiki](https://github.com/theagentplane/tokenops-wiki).

## Architecture

```
src/tokenops/
  control/   # SDK: governor, ledger, policies, client, attribution
  server/    # Standalone control plane HTTP
  ui/        # Admin + Dashboard
  config/    # Governance YAML loader + default seed
  providers/ # LLM complete helpers
```

- Entry agents register runs via `ControlPlaneClient` → plane `POST /v1/runs`
- Agents share spend through `TOKENOPS_DB` when using the same `run_id`

## Documentation

- [Control plane status](CONTROL_PLANE.md)
- [Control plane deploy](docs/control-plane-deploy.md)
- [Run attribution](docs/run-attribution.md)
- [Architecture](docs/architecture.md)
- [Wiki / examples](https://github.com/theagentplane/tokenops-wiki)
- [Why Token Governance?](docs/why-token-governance.md)
- [Code Navigation](docs/code-navigation.md)
- [Testing](docs/testing.md)
