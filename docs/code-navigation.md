# Code navigation

## Layout

| Path | Role |
|------|------|
| `src/tokenops/control/` | the governors: `run.py` (`tokenops_run`), `engine.py` (Governor), `ledger.py`, `policies/`, `crossing.py` (the Chronicle hook), `integration.py` (`wrap_complete`) |
| `src/tokenops/repositories/` | the only I/O: `ControlPlaneClient`, `LedgerEventWriter`, their types and errors |
| `src/tokenops/config/` | governance YAML loader and the packaged `default.yaml` |
| `src/tokenops/providers/` | LLM `complete` helpers (OpenAI, Anthropic) |
| `src/tokenops/adapters/` | LangChain adapter |
| `src/tokenops/demo.py` | `python -m tokenops.demo` |
| `examples/` | A2A agent stacks (being rewritten against a real control plane) |
| `tests/` | unit tests, `tests/contract` and `tests/e2e` (real control plane) |
| `docs/adr/` | architecture decision records |

## Make targets

| Target | Role |
|--------|------|
| `make lint` / `format` / `test` | ruff, mypy, pytest |
| `make demo-quick` | `python -m tokenops.demo` (no keys, no server) |
| `make sync-skills` | regenerate the editor copies of the integration skill |
| `make dist` / `check-dist` | build and `twine check` |

## Request path (SDK)

```
instrument_app    -> RequestContext (headers, payload, agent defaults)
tokenops_run      -> join the Chronicle trace, attribution, governance (pull or config=)
wrap_complete     -> pre_call -> (carry, compaction) -> admit -> chronicle wrap_llm(dispatch)
TokenOpsHook      -> crossing -> Observation -> Governor.observe -> Ledger.record -> writer
```

## Where to read next

- Architecture: [`docs/architecture.md`](architecture.md)
- Attribution and propagation: [`docs/trace-attribution.md`](trace-attribution.md)
- Halt: [`docs/halt.md`](halt.md)
- Policies, one file each: [`docs/policies/`](policies/)
- Decisions: [`docs/adr/`](adr/README.md)
