# Control plane deploy

Standalone TokenOps plane + SDK. Agent demos and compose overlays for research/summarize
or the triad live in [tokenops-wiki](https://github.com/theagentplane/tokenops-wiki).

## Shape

| Service | Command | Role |
|---------|---------|------|
| `tokenops` | `python -m tokenops.server` | Plane: `POST /v1/runs`, `GET /health`, shared SQLite |
| `ui` (optional profile) | `streamlit run src/tokenops/ui/app.py` | Admin + Dashboard |

Agents in your app (or wiki examples) set `TOKENOPS_URL=http://tokenops:7700` so they
**do not** mount `/v1/runs` locally.

## Env

| Var | Meaning |
|-----|---------|
| `TOKENOPS_URL` | Plane base URL for `ControlPlaneClient` |
| `TOKENOPS_DB` | Shared SQLite path |
| `TOKENOPS_CONFIG` | Governance seed YAML |
| `TOKENOPS_EMBEDDED=1` | Force in-process Store (tests) |

## Run compose (plane only)

```bash
docker compose up --build
# Also product UI (Admin + Dashboard)
docker compose --profile ui up --build
```

Plane: http://localhost:7700/health · UI: :8501

Without Docker:

```bash
make control-plane   # :7700
export TOKENOPS_URL=http://localhost:7700
make ui              # Admin + Dashboard on :8501
```

Or `make run` starts the plane + product UI.

## Examples (wiki)

```bash
# Sibling checkout
cd ../tokenops-wiki && make install
make run             # two-agent
make triad           # planner → researcher → writer
```

Field guide: https://github.com/theagentplane/tokenops-wiki/blob/main/docs/field-guide-add-tokenops.md

## SDK registration

```python
from tokenops import ControlPlaneClient

client = ControlPlaneClient.from_env()
reg = client.register_run(
    intent="my-intent",
    user_dims={"user_id": "alice"},
)
```

Prefer `entry_task_run_scope` in the entry agent so UIs can omit `run_id`.

## Out of scope (this MVP)

Full remote observe / governance admin over HTTP is not wired yet — agents still
open `Store` locally for ledger and policy config. The product UI reads/writes
the shared SQLite (`TOKENOPS_DB`) beside the plane process. Registration + plane
service + SDK client + compose is the split. See issue #18 (fat plane).
