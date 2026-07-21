# Control plane vs agent SDK (deploy shape)

Local `docker compose` matches the intended cloud layout: a **control-plane
service** owns run registration (and later observe/governance HTTP), while
**agents** keep the TokenOps SDK in-process for ledger, policies, and
`wrap_complete` — talking to the plane over HTTP for registration.

## What runs where

| Process | Image CMD | Role |
|---------|-----------|------|
| `tokenops` | `python -m tokenops.server` | Plane: `POST /v1/runs`, `GET /health`, shared SQLite |
| `research` / `summarize` | `python -m bench.servers.*` | Agents: A2A tasks; SDK + shared `TOKENOPS_DB` |
| `ui` (optional profile) | Streamlit | Registers via `ControlPlaneClient` → plane |

Shared volume mounts `TOKENOPS_DB=/data/tokenops.db`. Agents set
`TOKENOPS_URL=http://tokenops:7700` so they **do not** mount `/v1/runs`
themselves (`should_mount_run_registration()`).

## Env vars

| Var | Meaning |
|-----|---------|
| `TOKENOPS_URL` | Base URL of the control plane (e.g. `http://localhost:7700`) |
| `TOKENOPS_DB` | SQLite path (shared across plane + agents) |
| `TOKENOPS_EMBEDDED=1` | Force in-process `Store` in `ControlPlaneClient` (tests) |
| `TOKENOPS_PORT` | Plane listen port (default `7700`) |

## Register a run (SDK)

```python
from tokenops import ControlPlaneClient

client = ControlPlaneClient.from_env()  # TOKENOPS_URL or embedded Store
reg = client.register_run(
    intent="demo",
    user_dims={"user_id": "alice", "Country": "US"},
    mode="enforce",  # or omit
)
run_id = reg["run_id"]
# Then POST /v1/tasks to research with header X-TokenOps-Run-Id: run_id
```

Without `TOKENOPS_URL`, `from_env()` uses an embedded `Store` on `TOKENOPS_DB`
(same file agents use). Low-level `post_run` / `post_run_sync` remain as thin
HTTP helpers.

## Run compose

```bash
# Plane + research + summarize
docker compose up --build

# Also Streamlit UI
docker compose --profile ui up --build
```

Plane: http://localhost:7700/health · Research: :8001 · Summarize: :8002 · UI: :8501

Without Docker:

```bash
make control-plane   # :7700
export TOKENOPS_URL=http://localhost:7700
make research-server # :8001 (no /v1/runs mount)
make summarize-server
```

Or `make run` starts the plane, sets `TOKENOPS_URL`, then agents + UI.

## Out of scope (this MVP)

Full remote observe / governance admin over HTTP is not wired yet — agents still
open `Store` locally for ledger and policy config. Registration + plane service
+ SDK client + compose is the split.
