# Field guide: adding TokenOps to the triad bench

This walkthrough mirrors how TokenOps was wired into the **Planner → Researcher → Writer**
bench under [`examples/triad/`](../../examples/triad/). Code screenshots below were generated with
`python scripts/render_field_guide_snippets.py` → [`docs/guides/assets/`](assets/).

New to TokenOps? Start with the [onboarding guide](onboarding.md) (prereqs, bare-min
integrate, FAQ, current limits), then return here for the triad deep dive.

Related docs: [control-plane status](../control-plane-status.md),
[control-plane-deploy.md](../control-plane-deploy.md),
[run-attribution.md](../run-attribution.md).
Copilot skill: [integrate-tokenops](../../.cursor/skills/integrate-tokenops/SKILL.md).

## Shape

| Agent | Port | Role | TokenOps seams |
|-------|------|------|----------------|
| **Planner** | 8011 | Break goal into questions + outline; **entry** | `instrument_app` + `tokenops_run` → `wrap_complete` → A2A hops |
| **Researcher** | 8012 | Tools (`search` / `fetch`) gather facts | same `tokenops_run` + `@boundary` + crossing hook |
| **Writer** | 8013 | Final answer from findings | same `tokenops_run` → `wrap_complete` |

Naive agent logic lives in each `agent.py`. Instrumentation lives in each `server.py`
(and `researcher/tools.py` for tool boundaries).

```
UI: POST /v1/tasks  (task only — no run_id, no intent/mode)
        │
        ▼
     Planner  instrument_app(service, intent=..., provider=..., model=...)
              with tokenops_run():  # register-or-join + bind governance
              │ wrap_complete (plan LLM)
              │ post_task → merge_propagation_headers (run_id + parent span)
              ▼
         Researcher
              │ with tokenops_run():  # joins via X-TokenOps-Run-Id
              │ wrap_complete + @boundary(search/fetch)
              │ child spend → shared ledger (same run_id)
              ▼
           Planner
              │ post_task → Writer (same headers)
              ▼
            Writer
              │ with tokenops_run() → wrap_complete → shared ledger
              ▼
           Planner → TaskResponse (no parent cost rollup)
```

### Before: naive complete

Agent code stays injectable — no TokenOps imports in `agent.py`:

![Naive LLM call](assets/01-naive-complete.svg)

## Step 1 — Instrument the app + open a run

The UI calls **Planner** `POST /v1/tasks` with **task only**. Intent / mode / provider /
model come from the agent definition on `instrument_app` (or kwargs to `tokenops_run`).

![register_run](assets/02-register-run.svg)

```python
from tokenops import ControlPlaneClient, instrument_app, tokenops_run
from tokenops.control import wrap_complete, with_governance_errors
from tokenops.providers import complete

client = ControlPlaneClient.from_env()

async def handler(payload: dict, headers: Mapping[str, str]) -> dict:
    # Ambient RequestContext from instrument_app — no Store(path), no attr build.
    with tokenops_run(client=client) as bound:
        governed = wrap_complete(
            bound.governor, bound.controls, bound.attr,
            provider=cfg.provider, model=cfg.model,
            dispatch=complete, service=AGENT,
        )
        ...

app = create_a2a_app(..., handler=with_governance_errors(handler))
instrument_app(
    app,
    service=AGENT,
    intent="triad_plan",          # agent owns intent/mode — not the UI
    provider=cfg.provider,
    model=cfg.model,
)
```

`tokenops_run` register-or-joins: missing `X-TokenOps-Run-Id` → plane
`ControlPlaneClient.register_run`; present header → join that run and open a new span.

Downstream Researcher/Writer use the **same** `with tokenops_run(client=client):` —
headers from A2A `post_task` (`merge_propagation_headers`) carry the run id.

See `examples/triad/planner/server.py` and `examples/triad/client.py`
(`submit_goal_sync_with_meta` — UI path, no client register).

### Non-FastAPI

TokenOps does not yet ship middleware for Flask, Starlette-only, or other frameworks.
Bind ambient context yourself, then open the same scope:

```python
from tokenops import bind_request_context, tokenops_run, RequestContext

bind_request_context(RequestContext(
    headers=dict(headers),
    payload=payload,
    service="planner",
    intent="triad_plan",
    provider=...,
    model=...,
))
with tokenops_run():
    ...
```

Or pass `headers=` / `payload=` / `service=` / `intent=` as explicit kwargs to
`tokenops_run` (no ambient bind required).

## Step 2 — Propagate `run_id` on every A2A hop

Prefer ambient headers: A2A `post_task` / `post_task_sync` call
`merge_propagation_headers`, so outbound hops inherit `X-TokenOps-Run-Id` and
`X-TokenOps-Parent-Span-Id` from the current governance context.

```python
# Optional explicit override (usually unnecessary inside a governed handler):
from tokenops.control.context import RUN_ID_HEADER, PARENT_SPAN_ID_HEADER

headers = {RUN_ID_HEADER: run_id}
if parent_span_id:
    headers[PARENT_SPAN_ID_HEADER] = parent_span_id
```

Missing `run_id` on a hop soft-registers an `unattributed` run and logs
`tokenops.missing_run_id` (do not rely on that for the happy path — always propagate
from the entry agent).

## Step 3 — Use the bound handle (no nested scopes)

`tokenops_run` already binds registration, span, governor, and attribution.
Use `bound.governor` / `bound.controls` / `bound.attr` — do not hand-roll
`build_governor`, `build_attribution`, or a nested governance scope.

![governance_scope](assets/03-governance-scope.svg)

```python
with tokenops_run(client=client) as bound:
    run_id = bound.registration.run_id
    client.create_run(RunRecord(run_id=run_id, agent=AGENT, status="running", ...))
    governed = wrap_complete(
        bound.governor, bound.controls, bound.attr,
        provider=cfg.provider, model=cfg.model,
        dispatch=complete, service=AGENT,
    )
    ...
```

Shared ledger config comes from `ControlPlaneClient` / plane (`TOKENOPS_URL` +
`TOKENOPS_DB`) so **cost_budget** / **step_cap** apply across processes for one `run_id`.

## Step 4 — Wrap the LLM (`wrap_complete`)

![wrap_complete](assets/04-wrap-complete.svg)

```python
from tokenops.control import wrap_complete
from tokenops.providers import complete

governed = wrap_complete(
    bound.governor, bound.controls, bound.attr,
    provider=cfg.provider,
    model=cfg.model,
    dispatch=complete,
    service=AGENT,
)
agent.run(..., complete_fn=governed)
```

`wrap_complete` runs **pre_call** policies and emits LLM observations for **observe**
policies (`cost_budget`, `step_cap`, …).

## Step 5 — Tool boundaries (`@boundary` + crossing hook)

On the Researcher, tools are Chronicle boundaries so TokenOps can observe tool crossings
without changing the agent loop:

![boundary + crossing hook](assets/05-boundary-crossing.svg)

```python
from chronicle import InputState, boundary

@boundary(
    "search",
    kind="tool",
    extract_input=lambda query: InputState(
        messages=[], graph_state={"name": "search", "args": {"query": query}}
    ),
)
def invoke(query: str) -> SearchResult:
    return core.search(query, profile)
```

`instrument_app` installs the process-wide crossing hook (idempotent). You can also call
`tokenops.init()` or `install_crossing_hook()` once at startup.

`tool_freq` / `tool_output_cap` in the seed registry include `search` and `fetch`
(`examples/config/triad.yaml`).

## Step 6 — Delegates: spans only (no parent cost rollup)

A2A hops open a **new span** with `X-TokenOps-Parent-Span-Id` set from the caller
(ambient propagation). Child LLM/tool spend is already in the **shared ledger** for the
same `run_id`. The parent must **not** re-bill child `cost_micros` on its own observation
(that double-counted).

Refuse to delegate when the shared run budget is already exhausted
(`ledger.budget_left("run_llm_cap", ...)`) — still allowed as a local check.

## Step 7 — Errors and HTTP surface

```python
app = create_a2a_app(..., handler=with_governance_errors(handler))
if should_mount_run_registration():
    mount_run_registration(app, client.require_store())  # only when not using TOKENOPS_URL
instrument_app(app, service=AGENT, intent=..., provider=..., model=...)
```

`with_governance_errors` maps `Halt` / registration errors to HTTP responses the client can
inspect (`status`, `halt_reason`, `cost_micros`).

## Governance seed (demo)

`examples/config/triad.yaml` seeds:

- **cost_budget** on `run_llm_cap` ($0.50 / run) — easier to trip than the $2 two-agent default
- **step_cap** at 12 steps across the hoppy pipeline
- **tool_freq** registry `[search, fetch]`

Reset / reseed:

```bash
TOKENOPS_CONFIG=examples/config/triad.yaml make db-reset
```

## How to run

```bash
# Local processes
make demo-triad
# or: make control-plane && make writer-server && make researcher-server && make planner-server

# Docker (plane + triad; keeps default research/summarize compose intact)
docker compose -f docker-compose.yml -f docker-compose.triad.yml up --build tokenops planner researcher writer

# Client
export TOKENOPS_URL=http://localhost:7700
python -c "
from examples.triad import submit_goal_sync_with_meta
r, meta = submit_goal_sync_with_meta('http://localhost:8011', 'Explain mid-market CRM pricing')
print(meta['status'], meta['cost_micros'], r.summary[:200])
"

# Tests (mocked LLM)
python -m pytest tests/examples/test_triad_e2e.py -q
```

## Regenerating screenshots

```bash
python scripts/render_field_guide_snippets.py
# writes docs/guides/assets/{01..05}-*.{svg,png}
```

## Checklist for a new agent

1. Keep `agent.py` vanilla (injectable `complete_fn`).
2. `instrument_app(app, service=..., intent=..., provider=..., model=...)` once at startup
   (or `bind_request_context` + `tokenops_run` if not FastAPI).
3. In each handler: `with tokenops_run(client=client) as bound:` →
   `wrap_complete(bound.governor, bound.controls, bound.attr, ...)` →
   `with_governance_errors` on the HTTP handler.
4. UI / client sends **task only**; agent owns `intent` / `mode`.
5. Mark tools with Chronicle `@boundary`; rely on the crossing hook for observe.
6. Propagate `X-TokenOps-Run-Id` (and parent span) on every outbound A2A call
   (ambient `merge_propagation_headers` is enough).
7. Do **not** re-bill child spend on the parent (shared ledger already has it).
