# Code navigation

## Layout

| Path | Role |
|------|------|
| `src/tokenops/control/` | SDK: governor, ledger, policies, client, attribution, wraps |
| `src/tokenops/server/` | Standalone control plane (`POST /v1/runs`, `/health`) |
| `src/tokenops/ui/` | Admin + Dashboard (plane product UI) |
| `src/tokenops/config/` | Governance YAML loader + `default.yaml` seed |
| `src/tokenops/providers/` | LLM `complete` helpers |
| `examples/` | A2A benches (two-agent, triad, brief) + Chat/Simulator |
| `benchmarking/` | MetaGPT / browser-use live harness |

## Make targets

| Target | Role |
|--------|------|
| `make control-plane` | `python -m tokenops.server` |
| `make ui` | Admin + Dashboard |
| `make run` | Plane + Admin/Dashboard |
| `make demo` / `demo-triad` / `demo-brief` | Runnable A2A stacks |
| `make bench-ui` | Chat + Simulator |
| `make db-reset` | Clear SQLite + reseed from `TOKENOPS_CONFIG` |

## Request path (SDK)

```
instrument_app → RequestContext
tokenops_run  →  register-or-join + bind governor
  → wrap_complete / @boundary + crossing hook
```

## Docs

- Deploy: `docs/control-plane-deploy.md`
- Attribution: `docs/run-attribution.md`
- Examples field guide: `docs/guides/field-guide-add-tokenops.md`
