# Trace attribution

How a run is identified, who and why it is attributed to, and how identity crosses services.

Related: [architecture](architecture.md), [governance policy](governance-policy.md),
[halt](halt.md).

## A run is a trace

A run is one whole workflow. It is a [Chronicle](https://github.com/theagentplane/chronicle)
**trace**, and the only identifier is `trace_id` (32 lowercase hex characters). There is no
`run_id`, no run registration and no run record: nothing about a run is registered with, or
stored by, TokenOps.

## Two layers

| Layer | Set | Purpose |
|---|---|---|
| **Hop attribution** | once per `tokenops_run`, in memory | which user, agent and intent the spend belongs to; segment and budget matching |
| **Boundary observation** | each instrumented crossing | what this node did: `node_type`, `provider`, `model`, `tool`, cost, usage |

### Hop attribution

`tokenops_run` builds a frozen `RunRegistration(trace_id, intent, user_dims, mode)` for the hop:

| Field | Source | Notes |
|---|---|---|
| `trace_id` | the active Chronicle span, or the inbound `traceparent`, else a new trace | the only universal identity |
| `intent` | `tokenops_run(intent=...)`, else `instrument_app(intent=...)` | agent-owned; empty string if omitted; payload `intent` is ignored |
| `user_dims` | agent dims, then allow-listed payload keys (`user_id`, `user`) | opaque tags for `tag` budgets |
| `mode` | `tokenops_run(mode=...)`, else `instrument_app(mode=...)` | `enforce` (default) or `preview` |

Rules:

- **Agent arguments win over the payload.** The client sends the task only; it cannot set
  intent or mode.
- **A hop does not inherit** the entry hop's intent or dims. Each hop uses its own, so supply the
  dims your `tag` budgets key on at every hop.
- **Outside a bound scope, boundaries fail closed** (`RunNotRegisteredError`).
- `corpus_profile` and other bench-only fields are not governance dimensions.

### Boundary observation

Every crossing carries `trace_id` (ambient), `intent` and `user_dims` (read only), the span, the
**service** (mandatory: which agent owns the span) and `boundary_tags`.

`user_dims` answer *who and why*; boundary tags answer *what this node is doing*.

## Propagation across services

Hops share one trace through the W3C `traceparent` header, which Chronicle sends and reads. There
is no TokenOps header.

```python
import chronicle

chronicle.configure(
    control_plane_url="http://control-plane:8000", api_key="...",
    inject_hosts=["researcher.internal", "writer.internal"],   # default deny
)
chronicle.instrument_httpx()      # outbound httpx calls carry traceparent
```

Inbound, `tokenops_run` reads `traceparent` from the request headers (bound by `instrument_app`)
and joins that trace. A peer that is not in `inject_hosts` receives no header and starts its own
trace, so cross-agent budgets will not be shared with it: list every downstream host.

## Segments and budgets

A budget's `dimension` picks which attribute forms its segment key:

| Dimension | Segment key | Matches |
|---|---|---|
| `trace` | `trace:<trace_id>` | one run |
| `user` | `user:<user>` | one end user |
| `agent` | `agent:<service>` | one agent |
| `tenant` | `tenant:<tenant>` | one tenant |
| `tag` | `tag:<key>=<value>` | a `user_dims` tag |

The control plane treats segment keys as opaque; TokenOps computes them
(`control/ledger.py`, `segment_key_for`). Governance configuration is pulled from the control
plane per agent (`GET /v1/governance/{agent}`).

## In-process context

`contextvars` hold the active registration, span and governance for the request. Boundaries and
the hook read ambient context; handlers do not pass dims as arguments. Code:
`control/context.py`, `control/attribution.py`, `control/chronicle_trace_utils.py`.
