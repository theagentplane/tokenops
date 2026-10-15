# Migrating from TokenOps 0.4 to 1.0

1.0 is a clean break (issue [#162](https://github.com/theagentplane/tokenops/issues/162)).
TokenOps is the governors only: it stops carrying its own control plane, store, UI and run
model, and attaches to Chronicle 1.x and control plane 1.x. Every item below is also in the
[CHANGELOG](../CHANGELOG.md).

## 1. Install the suite

```bash
pip install "agent-tokenops>=1.0"            # pulls agent-chronicle>=1.1,<2 and agentplane-primitives 0.2.*
pip install "agentplane-control-plane>=1.0"  # only where you run the plane
```

The control plane needs to be 1.x: TokenOps 1.0 uses its governance, ledger and halt routes.
Old 0.2 planes and local `tokenops.db` files are not supported; delete any `tokenops.db`.

## 2. Identity: a run is a trace

| 0.4 | 1.0 |
|---|---|
| `run_id` (everywhere) | `trace_id` (a Chronicle trace, 32 hex characters) |
| `X-TokenOps-Run-Id`, `X-TokenOps-Parent-Span-Id` headers | the W3C `traceparent` header, sent by Chronicle |
| `POST /v1/runs` registration, `RunRecord` | nothing: attribution is built in memory per hop |
| `begin_entry_run`, `begin_downstream_run`, `begin_entry_task_run`, `mount_run_registration`, `post_run` | removed |
| dimension `run`, segment key `run:<id>` | dimension `trace`, segment key `trace:<id>` |

Do:

- Rename `run_id` to `trace_id` in your code and logs.
- Stop sending the TokenOps headers. Configure Chronicle to propagate:

  ```python
  chronicle.configure(control_plane_url=..., api_key=..., inject_hosts=["svc-a.internal"])
  chronicle.instrument_httpx()
  ```

- Change `dimension: run` to `dimension: trace` in governance YAML.
- A downstream hop no longer inherits the entry hop's `intent` and `user_dims`. Pass what your
  `tag` budgets need at every hop.

## 3. Configuration lives in the control plane

| 0.4 | 1.0 |
|---|---|
| `TOKENOPS_DB`, SQLite store, `make db-*` | the control plane's database |
| Admin UI (`make ui`) | the TokenOps tab of the control plane web page |
| `TOKENOPS_CONFIG` seed read by the SDK | `control-plane db seed --file ...` or the API |
| `ControlPlaneClient.from_env()` from `tokenops.control.client` | `tokenops.repositories.ControlPlaneClient.from_env()` |
| `TOKENOPS_URL` | `CONTROL_PLANE_URL` (plus `CONTROL_PLANE_API_KEY`) |

`tokenops_run(store=...)` is gone. Use `client=` (a plane) or `config=` (a governance dict, in
process).

## 4. Removed

- `tokenops.server`, `tokenops.ui` (Streamlit), the Docker and compose files, `benchmarking/`,
  and the demo asset scripts.
- The SQLite `Store`, `HttpStore`, the 0.2 `LedgerBackend`, `dev_plane`, `governance_cache`,
  `RunRecord`, `Segment`, `BudgetSpec`, `PolicyInstance`.
- `tokenops.control.trajectory` and the `trajectory_hint` implementation (the template was removed in 1.0.1, ADR 0005).
- `uvicorn` from the runtime dependencies.

## 5. Chronicle 1.x hooks

| 0.4 | 1.0 |
|---|---|
| `chronicle.session`, `get_session`, `reset_session`, `on_crossing` per session | one `Hook` on `chronicle.default_hooks` (`TokenOpsHook`) |
| `Input(arguments=..., messages=...)` for `extract_input` | return a plain mapping |
| `on_enter(boundary_id, kind, input)` | `on_enter(info: CallInfo)` |

`Halt` is still a `BaseException`; `Throttled` is now a `chronicle.AbortCall`.

## 6. Behaviour changes

- **Ledger writes** are queued and sent in the background by default
  (`tokenops_run(async_writes=False)` restores one synchronous write per crossing). A write is
  never retried when its outcome is unknown, so an outage can understate spend. Call
  `tokenops.flush_ledger_writes()` before a short-lived process exits.
- **Failure behaviour is explicit.** A configuration fetched earlier is used if the plane goes
  down; with none, `tokenops_run` raises.
- **Per-policy statistics** are not stored by the plane. `context_compaction` savings are on the
  envelope (`tokenops.compaction_tokens_*`).
- **The step window is per process**, so `step_cap` is per process and trace
  ([ADR 0004](adr/0004-policy-state-lives-in-process-except-shared-spend.md)).
- `python -m tokenops.demo` runs in process; it no longer launches a control plane.

## 7. Per consumer

| You are | Do |
|---|---|
| An agent author | Sections 2, 3 and 5; add `inject_hosts` for downstream services |
| Running the plane | Install control plane 1.x; seed or write governance through its API |
| A dashboard user | Use the control plane web page; the Streamlit UI is gone |
| Writing a custom policy | Read state through the `LedgerView`; the plane has no step window |
