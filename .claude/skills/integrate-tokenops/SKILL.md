---
name: integrate-tokenops
description: >-
  Add TokenOps run-aware token governance to a Python agent or multi-agent
  system: put a spend cap on a whole workflow, halt or steer a run before the
  next LLM call, and attribute cost per agent. Use when the user wants to cap
  agent spend, stop a runaway agent, budget a multi-agent run, or mentions
  TokenOps, tokenops_run, wrap_complete, register_run, crossing hooks, the
  control plane, or TOKENOPS_URL. Works for a single script, a LangChain or
  LangGraph agent, and FastAPI / A2A multi-agent stacks.
---

# Integrate TokenOps

Wire a spend cap and in-path enforcement into an agent stack.

Pick the smallest tier that covers the user's setup. Do not jump to Tier 3
because the project looks big. Most integrations start and stay at Tier 1.

| Tier | Use when | Adds |
|---|---|---|
| **1. One process** | A script, notebook, or single agent | ~10 lines, no server |
| **2. Shared plane** | Several agent processes must share one budget | A control plane on `:7700` |
| **3. Instrumented app** | FastAPI / A2A, run ids must flow across HTTP hops | `instrument_app` + header propagation |

Install: `pip install agent-tokenops` (Python 3.10+).

Runnable reference: `python -m tokenops.demo` (Tier 1, ships in the package),
`examples/triad/` and `examples/agents/` (Tier 3).

---

## The one thing to understand first

TokenOps governs a **run**, not a request. A run is one whole workflow. Every
model call and tool call in it shares one `run_id` and one ledger, so a
research to summarize to review pipeline stays inside a single budget even when
each step is a separate process.

Three moving parts:

- **`tokenops_run(...)`** opens or joins a run and hands back a `bound` handle.
- **`wrap_complete(...)`** wraps the function that calls the model. This is the
  enforcement point: detect, decide, and apply all run *before* the call.
- **The ledger** records spend and step count and carries the halt flag.

When a policy trips, `wrap_complete` raises `Halt`. Let it propagate, or catch
it and return a partial result. The run is flagged halted, so later calls on the
same `run_id` are refused even from another process.

---

## Tier 1 — one process

The whole integration. No server, no Docker, no config file.

```python
import os
os.environ.setdefault("TOKENOPS_EMBEDDED", "1")   # in-process ledger

from tokenops import ControlPlaneClient, tokenops_run
from tokenops.control import Halt, wrap_complete
from tokenops.providers import complete          # or your own dispatch fn

client = ControlPlaneClient.from_env()

with tokenops_run(client=client, service="my-agent", intent="research",
                  provider="openai", model="gpt-4o") as bound:
    governed = wrap_complete(
        bound.governor, bound.controls, bound.attr,
        provider="openai", model="gpt-4o",
        dispatch=complete, service="my-agent",
    )
    try:
        agent.run(..., complete_fn=governed)      # pass governed in, not complete
    except Halt as halt:
        print(f"run stopped: {halt}")
```

**The only invasive change is `complete_fn=governed`.** If the agent hard-codes
its model client, that is the one thing to refactor: make the completion
function injectable. Keep the agent itself vanilla.

### `dispatch` contract

Any callable with this shape works, so you are not tied to
`tokenops.providers.complete`:

```python
def dispatch(provider: str, model: str, messages, max_output_tokens=None, **kw):
    ...
    return ModelResponse(content=..., input_tokens=..., output_tokens=...)
```

`ModelResponse` lives in `tokenops.providers.types`. Report real token counts:
the ledger bills from them. For LangChain, `tokenops.adapters.langchain` already
provides a conforming dispatch.

### Set the budget

The seed config is `src/tokenops/config/default.yaml` ($2.00 per run). To change
it, copy that file, edit `limit_micros`, and point at it:

```bash
export TOKENOPS_CONFIG=my-governance.yaml
```

```yaml
governance:
  budgets:
    - id: run_llm_cap
      limit_micros: 500000        # $0.50 per run
      dimension: run
  policies:
    cost_budget:
      budget: run_llm_cap         # halts after the call that crosses the cap
    pre_call_worst_case:
      budget: run_llm_cap         # halts BEFORE a call that could cross it
      default_max_output: 1024
    step_cap:
      max_steps: 20
```

`cost_budget` is the backstop and can overshoot by one call.
`pre_call_worst_case` is the pre-emptive one. Enable both.

### Verify

```bash
python -m tokenops.demo
```

It runs the same loop ungoverned and governed, and prints both totals. Expect the
governed run to halt with `budget 'run_llm_cap' exhausted`.

---

## Tier 2 — several processes, one budget

Tier 1 keeps the ledger inside one process, so two processes would each get the
full cap. Point every process at one plane and one SQLite file.

```bash
export TOKENOPS_URL=http://localhost:7700   # every agent process
export TOKENOPS_DB=tokenops.db              # plane and agents share this file
python -m tokenops.server                   # the plane, on :7700
```

Agent code is unchanged from Tier 1: `ControlPlaneClient.from_env()` sees
`TOKENOPS_URL` and registers over HTTP instead of writing locally.

**Do not set `TOKENOPS_EMBEDDED=1` here.** It forces the in-process store and
silently defeats the shared cap.

Downstream processes must receive the run id, or they open a second run:

```python
from tokenops.control.context import PARENT_SPAN_ID_HEADER, RUN_ID_HEADER

headers = {RUN_ID_HEADER: run_id}
if parent_span_id:
    headers[PARENT_SPAN_ID_HEADER] = parent_span_id
```

Every hop uses the same `with tokenops_run(...)`. The entry agent registers the
run; downstream hops see the header and join it.

Admin and Dashboard UI: `make ui` on `:8501`.

---

## Tier 3 — FastAPI / A2A

`instrument_app` binds request context and installs the crossing hook once, so
handlers can call bare `tokenops_run()`.

```python
from tokenops import ControlPlaneClient, instrument_app, tokenops_run
from tokenops.control import with_governance_errors, wrap_complete
from tokenops.providers import complete

client = ControlPlaneClient.from_env()

async def handler(payload: dict, headers: Mapping[str, str]) -> dict:
    with tokenops_run(client=client) as bound:      # no kwargs needed
        governed = wrap_complete(
            bound.governor, bound.controls, bound.attr,
            provider=cfg.provider, model=cfg.model,
            dispatch=complete, service=AGENT,
        )
        agent.run(..., complete_fn=governed)

app = create_a2a_app(..., handler=with_governance_errors(handler))
instrument_app(app, service=AGENT, intent="triad_plan",
               provider=cfg.provider, model=cfg.model)
```

Rules that are easy to get wrong:

- The **client sends the task only**. No `run_id`, no intent, no mode. The entry
  agent owns those and passes them via `instrument_app`.
- Agents must **not** mount `/v1/runs` when `TOKENOPS_URL` is set. Guard with
  `should_mount_run_registration()`.
- **Never re-bill child spend on the parent.** The shared ledger already has it
  under the same `run_id`. Propagate headers, not costs.

Non-FastAPI frameworks have no middleware yet. Bind manually:

```python
from tokenops import RequestContext, bind_request_context, tokenops_run

bind_request_context(RequestContext(
    headers=dict(headers), payload=payload, service=AGENT, intent="...",
))
with tokenops_run():
    ...
```

### Tool calls

Model calls are covered by `wrap_complete`. Tool calls need a Chronicle
boundary, which the crossing hook turns into a ledger observation:

```python
from chronicle import InputState, boundary
from tokenops.control import install_crossing_hook

@boundary("search", kind="tool",
          extract_input=lambda q: InputState(
              messages=[], graph_state={"name": "search", "args": {"query": q}}))
def invoke(query: str) -> SearchResult:
    return core.search(query, profile)

install_crossing_hook()   # already done by instrument_app and tokenops.init
```

Reference: `examples/triad/researcher/tools.py`.

---

## Environment variables

| Variable | Meaning |
|---|---|
| `TOKENOPS_URL` | Plane base URL. Set it, and registration goes over HTTP. Aliases: `CONTROL_PLANE_URL`, `TOKENOPS_CONTROL_PLANE_URL`. |
| `TOKENOPS_EMBEDDED` | `1` forces the in-process store. Tier 1 and tests only. |
| `TOKENOPS_DB` | SQLite path shared by the plane and every agent. Defaults to `tokenops.db`. |
| `TOKENOPS_CONFIG` | Governance seed YAML. |

**Precedence footgun.** `ControlPlaneClient.from_env` takes the HTTP path only
when a URL is set **and** `TOKENOPS_EMBEDDED` is not `1`. So
`TOKENOPS_EMBEDDED=1` wins over `TOKENOPS_URL`, and setting both silently falls
back to a local SQLite file. Every process then gets its own full budget with no
error. When moving from Tier 1 to Tier 2, unset `TOKENOPS_EMBEDDED` first.

Confirm which path a process took:

```python
client = ControlPlaneClient.from_env()
print("embedded" if client.embedded else f"plane at {client.url}")
```

---

## Checklist

```
- [ ] Completion function is injectable (complete_fn / dispatch), agent stays vanilla
- [ ] tokenops_run wraps the unit of work you want budgeted
- [ ] wrap_complete wraps every model call inside it
- [ ] Halt is caught somewhere, or deliberately allowed to propagate
- [ ] Budget set in TOKENOPS_CONFIG, both cost_budget and pre_call_worst_case on
- [ ] Tier 2+: TOKENOPS_URL and TOKENOPS_DB shared, TOKENOPS_EMBEDDED unset
- [ ] Tier 2+: run id propagated on every hop
- [ ] Tier 3: tools carry a Chronicle @boundary
- [ ] Child spend is not re-billed on the parent
```

## Docs

- Onboarding: `docs/guides/onboarding.md`
- Triad deep dive: `docs/guides/field-guide-add-tokenops.md`
- Policies, one file each: `docs/policies/`
- Attribution: `docs/run-attribution.md`
- Deploy: `docs/control-plane-deploy.md`
