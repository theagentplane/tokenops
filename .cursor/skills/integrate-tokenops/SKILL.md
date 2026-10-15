---
name: integrate-tokenops
description: >-
  Add TokenOps run-aware token governance to a Python agent or multi-agent
  system: put a spend cap on a whole workflow, halt or steer a run before the
  next LLM call, and attribute cost per agent. Use when the user wants to cap
  agent spend, stop a runaway agent, budget a multi-agent run, or mentions
  TokenOps, tokenops_run, wrap_complete, crossing hooks, the control plane, or
  CONTROL_PLANE_URL. Works for a single script, a LangChain or LangGraph agent,
  and FastAPI / A2A multi-agent stacks.
---

<!-- Generated from .claude/skills/integrate-tokenops/SKILL.md by `make sync-skills`. Edit that file, not this one. -->

# Integrate TokenOps

Wire a spend cap and in-path enforcement into an agent stack.

Pick the smallest tier that covers the user's setup. Do not jump to Tier 3
because the project looks big. Most integrations start and stay at Tier 1.

| Tier | Use when | Adds |
|---|---|---|
| **1. One process** | A script, notebook, or single agent | ~10 lines, no server |
| **2. Shared control plane** | Several agent processes must share one budget, or you want the halt and spend visible | A running control plane and `CONTROL_PLANE_URL` |
| **3. Instrumented app** | FastAPI / A2A, the trace must flow across HTTP hops | `instrument_app` + Chronicle propagation |

Install: `pip install agent-tokenops` (Python 3.10+). It depends on
`agent-chronicle>=1.1`.

Runnable reference: `python -m tokenops.demo` (Tier 1, ships in the package).

---

## The one thing to understand first

TokenOps governs a **run**, not a request. A run is one whole workflow, and it
is a [Chronicle](https://github.com/theagentplane/chronicle) **trace**: the only
identifier is `trace_id`. Every model call and tool call in the run shares one
trace and one ledger, so a research to summarize to review pipeline stays inside
a single budget even when each step is a separate process.

Four moving parts:

- **`tokenops_run(...)`** joins the Chronicle trace (or starts one), builds the
  run's attribution, loads governance, and hands back a `bound` handle.
- **`wrap_complete(...)`** wraps the function that calls the model. Detect,
  decide and apply all run *before* the call.
- **The ledger** records spend and carries the halt flag. With a control plane it
  is shared across processes; without one it lives in the process.
- **The control plane** (optional, Tier 2+) stores governance configuration and
  the shared ledger. TokenOps has no server, store or UI of its own.

When a policy trips, `wrap_complete` raises `Halt`. Let it propagate, or catch it
and return a partial result. The trace is flagged halted
(`tokenops.halted` on the trace), so later calls are refused even from another
process.

---

## Tier 1: one process

The whole integration. No server, no Docker.

```python
from tokenops import tokenops_run
from tokenops.capabilities import wrap_complete
from tokenops.framework import Halt
from tokenops.providers import complete          # or your own dispatch fn

GOVERNANCE = {
    "governance": {
        "budgets": [{"id": "run_llm_cap", "limit_micros": 2_000_000, "dimension": "trace"}],
        "policies": {
            "cost_budget": {"budget": "run_llm_cap"},
            "pre_call_worst_case": {"budget": "run_llm_cap"},
            "step_cap": {"max_steps": 20},
        },
    }
}

with tokenops_run(config=GOVERNANCE, service="my-agent", intent="research",
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

`config=` also accepts the packaged defaults:
`tokenops.config.loader.load_governance_yaml()`.

### `dispatch` contract

Any callable with this shape works, so you are not tied to
`tokenops.providers.complete`:

```python
def dispatch(provider: str, model: str, messages, max_output_tokens=None, **kw):
    ...
    return ModelResponse(content=..., input_tokens=..., output_tokens=...)
```

`ModelResponse` lives in `tokenops.providers.types`. Report real token counts:
the ledger prices from them. For LangChain, `tokenops.adapters.langchain`
provides a conforming dispatch.

### Budgets and policies

`limit_micros` is integer micro-USD (`$1.00 == 1_000_000`).
`dimension` is `trace`, `user`, `agent`, `tenant` or `tag`; `trace` is the
per-run cap. Policy keys are the canonical IDs in `docs/policies/`.

`cost_budget` is the backstop and can overshoot by one call.
`pre_call_worst_case` is the pre-emptive one. Enable both.

### Verify

```bash
python -m tokenops.demo
```

It runs the same loop ungoverned and governed and prints both totals. Expect the
governed run to halt with `budget 'run_llm_cap' exhausted`.

---

## Tier 2: a control plane, several processes, one budget

Tier 1 keeps the ledger inside one process, so two processes would each get the
full cap. Run the AgentPlane control plane and point every process at it:

```bash
pip install agentplane-control-plane
control-plane serve                           # see its README for deployment
export CONTROL_PLANE_URL=http://localhost:8000
export CONTROL_PLANE_API_KEY=...              # a key with ingest + read scopes
```

Governance configuration lives in the control plane's database, not in your
code. Put it there with `control-plane db seed --file my.yaml`, the API
(`PUT /v1/budgets`, `PUT /v1/policies`; `admin` scope) or the TokenOps tab of its
web page. The agent pulls it on every run, `ETag` cached.

Agent code changes from `config=` to a client:

```python
from tokenops import tokenops_run
from tokenops.repositories import ControlPlaneClient

client = ControlPlaneClient.from_env()        # raises if CONTROL_PLANE_URL is unset

with tokenops_run(client=client, service="my-agent", intent="research",
                  provider="openai", model="gpt-4o") as bound:
    ...                                       # wrap_complete exactly as in Tier 1
```

How it behaves when the plane is down (explicit, tested):

- A configuration was fetched earlier: the last one is used and a WARNING is
  logged (`tokenops.governance_stale`).
- Nothing fetched yet: `tokenops_run` raises, so the hop never runs ungoverned.
- Ledger writes: spend and completion are queued and sent in the background
  (`async_writes=True`); admit and halt are synchronous. A batch is retried only
  when the request never reached the plane, never when the outcome is unknown
  (the plane does not deduplicate events), so an outage can understate spend.
  `LedgerEventWriter.stats` counts what was dropped. Call
  `tokenops.flush_ledger_writes()` before a short-lived process exits (it also
  runs at exit). Use `tokenops_run(async_writes=False)` for one synchronous
  write per crossing.

---

## Tier 3: FastAPI / A2A

`instrument_app` binds the request context and installs the governor hook once,
so handlers can call bare `tokenops_run()`.

```python
from tokenops import instrument_app, tokenops_run
from tokenops.capabilities import wrap_complete
from tokenops.interfaces import with_governance_errors
from tokenops.providers import complete
from tokenops.repositories import ControlPlaneClient

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

### One trace across HTTP hops

Hops join the same run through the W3C `traceparent` header, which Chronicle
sends and reads. There is no TokenOps header.

```python
import chronicle

chronicle.configure(
    control_plane_url="http://control-plane:8000",
    api_key="...",
    inject_hosts=["researcher.internal", "writer.internal"],   # default deny
)
chronicle.instrument_httpx()      # outbound httpx calls carry traceparent
```

Inbound, `tokenops_run` reads `traceparent` from the request headers and joins
that trace; with none it starts a new one.

Rules that are easy to get wrong:

- The **client sends the task only**. No trace id, intent or mode. The agent
  owns those and passes them via `instrument_app`.
- A hop's attribution (intent, `user_dims`, mode) comes from that hop's own
  arguments and the payload allow-list. A downstream hop does not inherit the
  entry hop's intent, so pass the dims that tag budgets use.
- **Never re-bill child spend on the parent.** The shared ledger already has it
  under the same trace.

Non-FastAPI frameworks have no middleware yet. Bind manually:

```python
from tokenops import RequestContext, bind_request_context, tokenops_run

bind_request_context(RequestContext(
    headers=dict(headers), payload=payload, service=AGENT, intent="...",
))
with tokenops_run(client=client):
    ...
```

### Tool calls

Model calls are covered by `wrap_complete`. Tool calls need a Chronicle
boundary, which the governor hook turns into a ledger observation:

```python
import chronicle

@chronicle.boundary("search", kind="tool")
def invoke(query: str) -> SearchResult:
    return core.search(query, profile)
```

`instrument_app` and `tokenops.init()` install the hook.

---

## Environment variables

| Variable | Meaning |
|---|---|
| `CONTROL_PLANE_URL` | Control plane base URL. Required for `ControlPlaneClient.from_env()`. |
| `CONTROL_PLANE_API_KEY` | Bearer key (scopes: `read`, `ingest`, `admin`). |
| `CHRONICLE_CONTROL_PLANE_URL`, `CHRONICLE_API_KEY` | Where Chronicle saves envelopes (set the same plane). |

There is no local-ledger fallback variable: with a plane configured, every
process governs against it; without one, pass `config=` (Tier 1).

---

## Checklist

```
- [ ] Completion function is injectable (complete_fn / dispatch), agent stays vanilla
- [ ] tokenops_run wraps the unit of work you want budgeted
- [ ] wrap_complete wraps every model call inside it
- [ ] Halt is caught somewhere, or deliberately allowed to propagate
- [ ] Budget configured: config= (Tier 1) or in the control plane (Tier 2+)
- [ ] Tier 2+: CONTROL_PLANE_URL and CONTROL_PLANE_API_KEY set on every process
- [ ] Tier 2+: Chronicle configured and inject_hosts lists the downstream services
- [ ] Tier 3: tools carry a Chronicle @boundary
- [ ] Child spend is not re-billed on the parent
```

## Docs

- Quickstart and FAQ: `docs/guides/onboarding.md`
- Policies, one file each: `docs/policies/`
- Attribution: `docs/trace-attribution.md`
- Halt semantics: `docs/halt.md`
- Migrating from 0.4: `docs/migration-0.4-to-1.0.md`
