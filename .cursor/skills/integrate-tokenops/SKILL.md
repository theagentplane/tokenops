---
name: integrate-tokenops
description: >-
  Integrate TokenOps governance into multi-agent systems: ControlPlaneClient.register_run,
  governance_scope, wrap_complete, Chronicle @boundary, install_crossing_hook, TOKENOPS_URL
  vs embedded Store, and plane vs agent split. Use when adding TokenOps to an agent stack,
  wiring the triad bench pattern, or when the user mentions register_run, wrap_complete,
  crossing hooks, control plane, or TOKENOPS_URL.
---

# Integrate TokenOps

Copyable procedure for GitHub Copilot, Claude Code, Cursor, or any assistant.
Reference implementation: **Planner → Researcher → Writer** under `bench/triad/`.
Full walkthrough: [`docs/field-guide-add-tokenops.md`](../../../docs/field-guide-add-tokenops.md).

## Plane vs agent (do not conflate)

| Layer | Owns | Does not own |
|-------|------|----------------|
| **Control plane** (`python -m tokenops.server`, `:7700`) | `POST /v1/runs`, shared SQLite (`TOKENOPS_DB`), Admin/Dashboard | Agent loops, LLM calls, tools |
| **Agent process** (TokenOps SDK in-process) | `wrap_complete`, ledger/policies, Chronicle boundaries, A2A tasks | Ad-hoc run IDs; mounting `/v1/runs` when `TOKENOPS_URL` is set |

Clients register via `ControlPlaneClient`, then send `X-TokenOps-Run-Id` on every A2A hop.
Agents share one ledger file so **cost_budget** / **step_cap** apply across processes.

## Env

| Var | Meaning |
|-----|---------|
| `TOKENOPS_URL` | Remote plane base URL (e.g. `http://localhost:7700`) → HTTP `register_run` |
| `TOKENOPS_EMBEDDED=1` | Force in-process `Store` (tests / single-process) |
| `TOKENOPS_DB` | SQLite path shared by plane + agents |
| `TOKENOPS_CONFIG` | YAML for governance seed (e.g. `src/tokenops/config/triad.yaml`) |

- **Production / multi-process:** set `TOKENOPS_URL`; agents must **not** mount `/v1/runs`.
- **Tests:** `TOKENOPS_EMBEDDED=1` (or omit URL) so `from_env()` uses embedded Store.

## Checklist

```
TokenOps integration:
- [ ] 1. Client: ControlPlaneClient.register_run → run_id
- [ ] 2. Propagate X-TokenOps-Run-Id (+ parent span) on every A2A call
- [ ] 3. Server: downstream_run_scope → build_governor(..., store=store) → governance_scope
- [ ] 4. LLM: wrap_complete(..., dispatch=complete) as complete_fn
- [ ] 5. Tools: Chronicle @boundary + install_crossing_hook() once per process
- [ ] 6. Parent: observation_from_delegate for child cost_micros
- [ ] 7. Keep agent.py vanilla (injectable complete_fn / tools)
```

## Step 1 — Register the run

```python
from tokenops.control.client import ControlPlaneClient
# or: from tokenops import ControlPlaneClient

reg = ControlPlaneClient.from_env().register_run(
    intent="my-intent",
    user_dims={"user_id": "alice"},
)
run_id = reg["run_id"]
```

See `bench/triad/client.py` (`submit_goal_sync_with_meta`).

## Step 2 — Propagate run_id

```python
from tokenops.control.context import RUN_ID_HEADER, PARENT_SPAN_ID_HEADER

headers = {RUN_ID_HEADER: run_id}
if parent_span_id:
    headers[PARENT_SPAN_ID_HEADER] = parent_span_id
# POST /v1/tasks with these headers
```

Entry agent: require the header (fail closed). Downstream: `downstream_run_scope(store, headers=..., service=...)`.

## Step 3 — Governance scope + governor

```python
with downstream_run_scope(store, headers=headers, service=AGENT):
    reg = current_registration()
    attr = build_attribution(reg, service=AGENT)
    governor = build_governor(
        store.governance_config_for(AGENT),
        price,
        ApplyControls(),  # or PreviewControls()
        store=store,      # shared SQLite across processes
        enforce=True,
    )
    governor.ledger.open_run(run_id)
    with governance_scope(governor, attr, provider=..., model=...):
        ...
```

`store=store` is required for cross-process budget/step caps.

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

Runs **pre_call** policies then **observe** on completion.

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

# Once per server process (module import / create_app):
install_crossing_hook()  # Chronicle on_crossing → Governor.observe
```

Reference: `bench/triad/researcher/tools.py`, `bench/triad/researcher/server.py`.

## Step 6 — Delegate rollup

```python
from tokenops.control import observation_from_delegate

governor.observe(
    observation_from_delegate(
        attr,
        boundary_id="delegate_researcher",  # or delegate_writer
        rolled_up_cost_micros=child_cost,
        ts=time.time(),
        service="planner",
    )
)
```

Refuse outbound delegates when `ledger.budget_left("run_llm_cap", ...)` is exhausted.

## Step 7 — HTTP surface

```python
app = create_a2a_app(..., handler=with_governance_errors(handler))
if should_mount_run_registration():  # False when TOKENOPS_URL is set
    mount_run_registration(app, store)
install_crossing_hook()
```

## Verify

```bash
# Local triad demo
TOKENOPS_CONFIG=src/tokenops/config/triad.yaml make db-reset
make run-triad

# Offline e2e (mocked LLM)
python -m pytest tests/test_triad_e2e.py -q
```

## Docs

- Field guide + screenshots: `docs/field-guide-add-tokenops.md`
- Deploy / env: `docs/control-plane-deploy.md`, `CONTROL_PLANE.md`
- Attribution: `docs/run-attribution.md`
- Policies: `docs/policies/`, `docs/testing.md`
