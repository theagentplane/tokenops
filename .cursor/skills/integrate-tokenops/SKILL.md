---
name: integrate-tokenops
description: >-
  Integrate TokenOps governance into multi-agent systems: entry_task_run_scope /
  ControlPlaneClient.register_run, governance_scope, wrap_complete, Chronicle @boundary,
  install_crossing_hook, TOKENOPS_URL vs embedded Store, and plane vs agent split. Use when
  adding TokenOps to an agent stack, wiring the triad bench pattern, or when the user
  mentions register_run, wrap_complete, crossing hooks, control plane, or TOKENOPS_URL.
---

# Integrate TokenOps

Copyable procedure for GitHub Copilot, Claude Code, Cursor, or any assistant.

- **Core library:** [theagentplane/tokenops](https://github.com/theagentplane/tokenops) (`pip install`)
- **Runnable reference (triad / two-agent):** [theagentplane/tokenops-wiki](https://github.com/theagentplane/tokenops-wiki)
  — `examples/triad/`, field guide `docs/field-guide-add-tokenops.md`

## Plane vs agent (do not conflate)

| Layer | Owns | Does not own |
|-------|------|----------------|
| **Control plane** (`python -m tokenops.server`, `:7700`) | `POST /v1/runs`, shared SQLite (`TOKENOPS_DB`), Admin/Dashboard | Agent loops, LLM calls, tools |
| **Agent process** (TokenOps SDK in-process) | `wrap_complete`, ledger/policies, Chronicle boundaries, A2A tasks | Ad-hoc run IDs; mounting `/v1/runs` when `TOKENOPS_URL` is set |

**UI path:** client calls the **entry** agent `POST /v1/tasks` **without** `run_id`.
The entry agent opens the run via `entry_task_run_scope` → `ControlPlaneClient.register_run`
→ plane `POST /v1/runs` (or embedded Store). Downstream hops inherit headers via
`merge_propagation_headers`. Agents share one ledger file so **cost_budget** / **step_cap**
apply across processes. Child spend hits that ledger once — **no parent cost rollup**.

## Env

| Var | Meaning |
|-----|---------|
| `TOKENOPS_URL` | Remote plane base URL (e.g. `http://localhost:7700`) → HTTP `register_run` |
| `TOKENOPS_EMBEDDED=1` | Force in-process `Store` (tests / single-process) |
| `TOKENOPS_DB` | SQLite path shared by plane + agents |
| `TOKENOPS_CONFIG` | YAML for governance seed (core: `src/tokenops/config/default.yaml`; demos: wiki `examples/config/`) |

- **Production / multi-process:** set `TOKENOPS_URL`; agents must **not** mount `/v1/runs`.
- **Tests:** `TOKENOPS_EMBEDDED=1` (or omit URL) so `from_env()` uses embedded Store.

## Checklist

```
TokenOps integration:
- [ ] 1. Entry agent: entry_task_run_scope (UI omits run_id)
- [ ] 2. Propagate X-TokenOps-Run-Id (+ parent span) on every A2A hop
- [ ] 3. Downstream: downstream_run_scope → build_governor(..., store=store) → governance_scope
- [ ] 4. LLM: wrap_complete(..., dispatch=complete) as complete_fn
- [ ] 5. Tools: Chronicle @boundary + install_crossing_hook() once per process
- [ ] 6. Do NOT observation_from_delegate / parent cost rollup (shared ledger)
- [ ] 7. Keep agent.py vanilla (injectable complete_fn / tools)
```

## Step 1 — Entry agent registers the run

```python
from tokenops.control import entry_task_run_scope
from tokenops.control.context import current_registration

# Inside entry agent handler (Planner / Research):
with entry_task_run_scope(store, headers=headers, payload=payload, service=AGENT):
    reg = current_registration()
    run_id = reg.run_id
    ...
```

UI / bench clients should **not** call `/v1/runs` for the default flow — see wiki
`examples/triad/client.py` and `examples/a2a/client.py`.

## Step 2 — Propagate run_id

Prefer ambient headers: A2A `post_task` merges `propagation_headers()` from context.

```python
from tokenops.control.context import RUN_ID_HEADER, PARENT_SPAN_ID_HEADER

headers = {RUN_ID_HEADER: run_id}
if parent_span_id:
    headers[PARENT_SPAN_ID_HEADER] = parent_span_id
```

Entry: `entry_task_run_scope`. Downstream: `downstream_run_scope(store, headers=..., service=...)`.

## Step 3 — Governance scope + governor

```python
with downstream_run_scope(store, headers=headers, service=AGENT):
    reg = current_registration()
    attr = build_attribution(reg, service=AGENT)
    governor = build_governor(
        store.governance_config_for(AGENT),
        price,
        ApplyControls(),
        store=store,
        enforce=True,
    )
    governor.ledger.open_run(run_id)
    with governance_scope(governor, attr, provider=..., model=...):
        ...
```

## Step 4 — Wrap the LLM

```python
from tokenops.control import wrap_complete
from tokenops.providers import complete

governed = wrap_complete(
    governor, controls, attr,
    provider=cfg.provider, model=cfg.model,
    dispatch=complete, service=AGENT,
)
agent.run(..., complete_fn=governed)
```

## Step 5 — Tool boundaries + crossing hook

```python
from chronicle import InputState, boundary
from tokenops.control import install_crossing_hook

@boundary(
    "search",
    kind="tool",
    extract_input=lambda query: InputState(
        messages=[], graph_state={"name": "search", "args": {"query": query}}
    ),
)
def invoke(query: str) -> SearchResult:
    return core.search(query, profile)

install_crossing_hook()
```

Reference: wiki `examples/triad/researcher/tools.py`.

## Step 6 — Delegates: spans only (no parent cost rollup)

Child LLM/tool spend is already in the **shared ledger** for the same `run_id`.
Do **not** call `observation_from_delegate` to re-add `cost_micros`.

## Step 7 — HTTP surface

```python
app = create_a2a_app(..., handler=with_governance_errors(handler))
if should_mount_run_registration():  # False when TOKENOPS_URL is set
    mount_run_registration(app, store)
install_crossing_hook()
```

## Verify

```bash
# Clone wiki examples (sibling of tokenops)
cd ../tokenops-wiki && make install
TOKENOPS_CONFIG=examples/config/triad.yaml make db-reset
make triad
```

## Docs

- Core deploy: https://github.com/theagentplane/tokenops/blob/main/docs/control-plane-deploy.md
- Field guide + screenshots: https://github.com/theagentplane/tokenops-wiki/blob/main/docs/field-guide-add-tokenops.md
- Attribution: https://github.com/theagentplane/tokenops/blob/main/docs/run-attribution.md
