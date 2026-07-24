---
name: integrate-tokenops
description: >-
  Integrate TokenOps governance into multi-agent systems: instrument_app /
  tokenops_run / ControlPlaneClient, wrap_complete, Chronicle @boundary,
  install_crossing_hook, TOKENOPS_URL vs embedded Store, and plane vs agent split.
  Use when adding TokenOps to an agent stack, wiring the triad bench pattern, or
  when the user mentions register_run, wrap_complete, crossing hooks, control plane,
  or TOKENOPS_URL.
---

# Integrate TokenOps

Copyable procedure for GitHub Copilot, Claude Code, Cursor, or any assistant.

- **Platform contract (read first):** [`docs/guides/onboarding.md`](../../docs/guides/onboarding.md)
- **Core library:** [theagentplane/tokenops](https://github.com/theagentplane/tokenops) (`pip install`)
- **Runnable reference only (triad / two-agent):** `examples/triad/`, `examples/agents/` —
  field guide `docs/guides/field-guide-add-tokenops.md`

TokenOps does **not** require `agent.run`, `create_a2a_app`, or A2A. Those appear in
`examples/` as one host shape. The platform surface is: `ControlPlaneClient` →
`tokenops_run` → `wrap_complete` → propagate `X-TokenOps-Run-Id`.


## Plane vs agent (do not conflate)

| Layer | Owns | Does not own |
|-------|------|----------------|
| **Control plane** (`python -m tokenops.server`, `:7700`) | `POST /v1/runs`, shared SQLite (`TOKENOPS_DB`), Admin/Dashboard | Agent loops, LLM calls, tools |
| **Agent process** (TokenOps SDK in-process) | `tokenops_run`, `wrap_complete`, ledger/policies, Chronicle boundaries, A2A tasks | Ad-hoc run IDs; mounting `/v1/runs` when `TOKENOPS_URL` is set |

**UI path:** client calls the **entry** agent `POST /v1/tasks` with **task only**
(no `run_id`, no intent/mode). The entry agent opens the run via `tokenops_run` →
`ControlPlaneClient.register_run` → plane `POST /v1/runs` (or embedded Store).
Downstream hops inherit headers via `merge_propagation_headers`. Agents share one
ledger file so **cost_budget** / **step_cap** apply across processes. Child spend
hits that ledger once — **no parent cost rollup**.

## Env

| Var | Meaning |
|-----|---------|
| `TOKENOPS_URL` | Remote plane base URL (e.g. `http://localhost:7700`) → HTTP `register_run` |
| `TOKENOPS_EMBEDDED=1` | Force in-process `Store` (tests / single-process) |
| `TOKENOPS_DB` | SQLite path shared by plane + agents |
| `TOKENOPS_CONFIG` | YAML for governance seed (core: `src/tokenops/config/default.yaml`; demos: `examples/config/`) |

- **Production / multi-process:** set `TOKENOPS_URL`; agents must **not** mount `/v1/runs`.
- **Tests:** `TOKENOPS_EMBEDDED=1` (or omit URL) so `from_env()` uses embedded Store.

## Checklist

```
TokenOps integration (platform):
- [ ] 1. ControlPlaneClient.from_env()
- [ ] 2. with tokenops_run(...) as bound:   # register-or-join
- [ ] 3. governed = wrap_complete(bound.governor, bound.controls, bound.attr, ...)
- [ ] 4. Call governed(...) wherever you call the model (any framework)
- [ ] 5. Propagate X-TokenOps-Run-Id (+ parent span) on every hop
- [ ] 6. Do NOT re-bill child spend on the parent (shared ledger already has it)
- [ ] 7. Agent owns intent/mode; callers send work (task) only
Optional:
- [ ] instrument_app (FastAPI RequestContext + crossing hook)
- [ ] Chronicle @boundary on tools
- [ ] with_governance_errors only if you want Halt/Throttled → HTTP JSON
```

## Step 1 — tokenops_run + wrap_complete (required)

```python
from tokenops import ControlPlaneClient, tokenops_run
from tokenops.control import wrap_complete
from tokenops.providers import complete

client = ControlPlaneClient.from_env()

with tokenops_run(
    client=client,
    headers=incoming_headers,
    payload=payload,
    service=AGENT,
    intent="triad_plan",
) as bound:
    governed = wrap_complete(
        bound.governor, bound.controls, bound.attr,
        provider=cfg.provider, model=cfg.model,
        dispatch=complete, service=AGENT,
    )
    resp = governed(cfg.provider, cfg.model, messages)
```

### FastAPI (optional)

```python
from tokenops import instrument_app

instrument_app(app, service=AGENT, intent="triad_plan",
               provider=cfg.provider, model=cfg.model)
# then: with tokenops_run(client=client) as bound:  # context from middleware
```

### Demo / A2A host shape (examples only — not required)

```python
from tokenops.control import with_governance_errors
# examples.a2a.server.create_a2a_app + handler=with_governance_errors(...)
# injectable agent.run(..., complete_fn=governed) — local bench convention
```

UI / bench clients should **not** call `/v1/runs` for the default flow — see
`examples/triad/client.py` and `examples/a2a/client.py`.

### Non-FastAPI

```python
from tokenops import RequestContext, bind_request_context, tokenops_run

bind_request_context(RequestContext(
    headers=dict(headers), payload=payload, service=AGENT, intent="...",
))
with tokenops_run():
    ...
```

Or pass kwargs explicitly to `tokenops_run(headers=..., payload=..., service=..., intent=...)`.

## Step 2 — Propagate run_id

Prefer ambient headers: A2A `post_task` merges `propagation_headers()` from context.

```python
from tokenops.control.context import RUN_ID_HEADER, PARENT_SPAN_ID_HEADER

headers = {RUN_ID_HEADER: run_id}
if parent_span_id:
    headers[PARENT_SPAN_ID_HEADER] = parent_span_id
```

Every hop uses the same `with tokenops_run(...):` — entry registers, downstream joins.

## Step 3 — Bound handle (no nested scopes)

Do not hand-roll attribution or a separate governance scope. Use `bound.*` from
`tokenops_run`.

## Step 4 — Wrap the LLM

```python
from tokenops.control import wrap_complete
from tokenops.providers import complete

governed = wrap_complete(
    bound.governor, bound.controls, bound.attr,
    provider=cfg.provider, model=cfg.model,
    dispatch=complete, service=AGENT,
)
resp = governed(cfg.provider, cfg.model, messages)
# Or inject governed into your framework — no required agent.run API.
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

install_crossing_hook()  # also done by instrument_app / tokenops.init
```

Reference: `examples/triad/researcher/tools.py`.

## Step 6 — Delegates: spans only (no parent cost rollup)

Child LLM/tool spend is already in the **shared ledger** for the same `run_id`.
Propagate run/span headers on hops; do **not** re-add child `cost_micros` on the parent.

## Step 7 — HTTP surface

```python
app = create_a2a_app(..., handler=with_governance_errors(handler))
if should_mount_run_registration():  # False when TOKENOPS_URL is set
    mount_run_registration(app, client.require_store())
instrument_app(app, service=AGENT, intent=..., provider=..., model=...)
```

## Verify

```bash
make install
TOKENOPS_CONFIG=examples/config/triad.yaml make db-reset
make demo-triad
```

## Docs

- Deploy: `docs/control-plane-deploy.md`
- Field guide + screenshots: `docs/guides/field-guide-add-tokenops.md`
- Attribution: `docs/run-attribution.md`
