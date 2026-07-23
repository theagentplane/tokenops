# Control plane deploy

Standalone TokenOps plane + SDK. Agent demos and compose overlays live in-repo under
[`examples/`](../examples/) (`docker-compose.examples.yml`, `docker-compose.triad.yml`).

## Shape

| Service | Command | Role |
|---------|---------|------|
| `tokenops` | `python -m tokenops.server` | Plane: `POST /v1/runs`, `GET /health`, shared SQLite |
| `ui` (optional profile) | `streamlit run src/tokenops/ui/app.py` | Admin + Dashboard |

Agents in your app (or `examples/`) set `TOKENOPS_URL=http://tokenops:7700` so they
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

## Examples

```bash
make install
make demo            # two-agent (research → summarize)
make demo-triad      # planner → researcher → writer
make demo-brief      # scout → analyst → editor
# Docker:
docker compose -f docker-compose.examples.yml up --build
docker compose -f docker-compose.examples.yml -f docker-compose.triad.yml up --build \
  tokenops planner researcher writer
```

Field guide: [`docs/guides/field-guide-add-tokenops.md`](guides/field-guide-add-tokenops.md).

## SDK registration

```python
from tokenops import ControlPlaneClient

client = ControlPlaneClient.from_env()
reg = client.register_run(
    intent="my-intent",
    user_dims={"user_id": "alice"},
)
```

Prefer `tokenops_run` in the entry agent so UIs can omit `run_id` (and omit
intent/mode — those come from `instrument_app` / agent kwargs).

## Non-FastAPI

TokenOps does not yet ship middleware for other frameworks. Use
`bind_request_context(...)` then `with tokenops_run():`, or pass kwargs
explicitly to `tokenops_run`.

## Out of scope (this MVP)

Full remote observe / governance admin over HTTP is not wired yet — agents still
open `Store` locally for ledger and policy config. The product UI reads/writes
the shared SQLite (`TOKENOPS_DB`) beside the plane process. Registration + plane
service + SDK client + compose is the split. See issue #18 (fat plane).
