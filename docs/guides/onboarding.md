# Onboarding

Prerequisites, the minimum integration, and the questions people ask first.

| You want | Go to |
|---|---|
| Copy-paste integration | [the integration skill](../../.claude/skills/integrate-tokenops/SKILL.md) |
| How it works | [Architecture](../architecture.md), [trace attribution](../trace-attribution.md) |
| What stops a run, and how to resume | [Halt](../halt.md) |
| Each policy | [`docs/policies/`](../policies/) |
| Coming from 0.4 | [Migration](../migration-0.4-to-1.0.md) |

## The model in four lines

- **Govern the run, not the request.** One Chronicle trace (`trace_id`) spans every model call,
  tool call and agent hop of a workflow, and one budget covers all of it.
- **Three pieces.** The [control plane](https://github.com/theagentplane/control-plane) stores
  configuration and the shared ledger. [Chronicle](https://github.com/theagentplane/chronicle)
  gives the run its identity and records it. TokenOps decides, in your process, whether the next
  call may happen.
- **`tokenops_run` joins the trace.** It builds the hop's attribution from its own `intent`,
  `user_dims` and `mode`; nothing is registered with the plane.
- **`wrap_complete` is the enforcement point.** The check runs before the call and raises `Halt`
  when the run is out.

## Prerequisites

- Python 3.10 to 3.13 and `pip install agent-tokenops` (pulls `agent-chronicle>=1.1`).
- **One process, no server:** nothing else. Pass `config=` to `tokenops_run`.
- **Several processes, or visibility:** a running control plane 1.x
  (`pip install agentplane-control-plane`, then `control-plane serve`), and on every agent:

  ```bash
  export CONTROL_PLANE_URL=http://localhost:8000
  export CONTROL_PLANE_API_KEY=...        # scopes: read, ingest (admin to write configuration)
  ```

## Minimum integration

```python
from tokenops import tokenops_run
from tokenops.control import Halt, wrap_complete
from tokenops.providers import complete
from tokenops.repositories import ControlPlaneClient

client = ControlPlaneClient.from_env()

with tokenops_run(client=client, service="my-agent", intent="research",
                  provider="openai", model="gpt-4o") as bound:
    governed = wrap_complete(bound.governor, bound.controls, bound.attr,
                             provider="openai", model="gpt-4o",
                             dispatch=complete, service="my-agent")
    try:
        agent.run(..., complete_fn=governed)
    except Halt as stopped:
        print(f"run stopped: {stopped}")
```

Without a control plane, replace `client=client` with `config=<governance dict>`; see
`python -m tokenops.demo`.

Where the budget comes from: the control plane's database (`control-plane db seed --file`,
`PUT /v1/budgets`, `PUT /v1/policies`, or its TokenOps tab). The agent pulls it on every run.

## FAQ

### Do the entry agent and the downstream agents call different functions?

No. Every hop uses `with tokenops_run(...)`. A downstream hop receives the trace through
Chronicle's `traceparent` header and joins it; the entry hop starts it. Configure
`chronicle.configure(inject_hosts=[...])` and `chronicle.instrument_httpx()` so the header is sent.

### Does a downstream hop inherit the entry agent's intent?

No. Each hop's attribution comes from its own arguments and the payload allow-list (`user_id`,
`user`). Pass the dims your `tag` budgets key on at every hop.

### What happens when the control plane is down?

A configuration fetched earlier is used (WARNING `tokenops.governance_stale`). With none cached,
`tokenops_run` raises: a hop never runs ungoverned. Ledger writes are queued and may be dropped
and counted during an outage, which can understate spend; see
[ADR 0003](../adr/0003-ledger-spend-writes-are-asynchronous.md).

### Where is my halt?

On the trace: `GET /v1/traces/{trace_id}` shows `tokenops.halted` and `tokenops.halt_reason`
in `attributes`, the TokenOps tab lists halted traces, and
`ControlPlaneClient.halt_status(trace_id)` reads it.

### Do I construct a store or a database?

No. TokenOps has none. Everything persistent is in the control plane.

## Current limits

TokenOps 1.0 is the governors only. Honest limits:

- A policy's step window is per process and per trace; `step_cap` is not a run-wide cap across
  processes ([ADR 0004](../adr/0004-policy-state-lives-in-process-except-shared-spend.md)).
- `trajectory_hint` is a known template that is disabled.
- Spend is understated, not overstated, by lost writes: events are never retried when the outcome
  is unknown.
- The governors attach through Chronicle hooks, but `wrap_complete` and `wrap_stream` are still
  TokenOps wrappers ([#173](https://github.com/theagentplane/tokenops/issues/173)).
- `control-plane` on SQLite can answer a TokenOps agent and Chronicle writing at once with
  `database is locked`
  ([control-plane#28](https://github.com/theagentplane/control-plane/issues/28)); use a database
  that supports concurrent writers in production.
