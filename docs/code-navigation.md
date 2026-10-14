# Code navigation

## Layout

| Path | Role |
|------|------|
| `src/tokenops/control/` | SDK: governor, ledger, policies, client, attribution, wraps |
| `src/tokenops/config/` | Governance YAML loader + `default.yaml` seed |
| `src/tokenops/providers/` | LLM `complete` helpers |
| `examples/` | A2A agent stacks (rewritten in #162) |

## Make targets

| Target | Role |
|--------|------|
| `make lint` / `format` / `test` | ruff, mypy, pytest |
| `make demo-quick` | `python -m tokenops.demo` (no keys, no server) |

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
