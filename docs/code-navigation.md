# Code navigation

## Layout (core package)

| Path | Role |
|------|------|
| `src/tokenops/control/` | SDK: governor, ledger, policies, client, attribution, wraps |
| `src/tokenops/server/` | Standalone control plane (`POST /v1/runs`, `/health`) |
| `src/tokenops/ui/` | Admin + Dashboard (plane product UI) |
| `src/tokenops/config/` | Governance YAML loader + `default.yaml` seed |
| `src/tokenops/providers/` | LLM `complete` helpers |

Runnable A2A demos, Chat/Simulator, and benchmarking live in
[tokenops-wiki](https://github.com/theagentplane/tokenops-wiki) under `examples/` and `benchmarking/`.

## Make targets

| Target | Role |
|--------|------|
| `make control-plane` | `python -m tokenops.server` |
| `make ui` | Admin + Dashboard |
| `make run` | Plane + Admin/Dashboard |
| `make db-reset` | Clear SQLite + reseed from `TOKENOPS_CONFIG` |

## Request path (SDK)

```
ControlPlaneClient.register_run / POST /v1/runs  →  plane
entry_task_run_scope / downstream_run_scope
  → build_governor(..., store=store)
  → wrap_complete / @boundary + install_crossing_hook
```

## Docs

- Deploy: `docs/control-plane-deploy.md`
- Attribution: `docs/run-attribution.md`
- Examples field guide: https://github.com/theagentplane/tokenops-wiki/blob/main/docs/field-guide-add-tokenops.md
