# Onboarding: TokenOps as a platform

New to TokenOps? Start here. This page covers the mental model, prerequisites,
the **platform** integration surface (not our demo benches), FAQ, and what
TokenOps is **not** doing today.

| Go deeper | Doc |
|-----------|-----|
| Triad bench walkthrough (examples only) | [Field guide](field-guide-add-tokenops.md) |
| Job-by-job plane status | [Control plane status](../control-plane-status.md) |
| Copilot / agent checklist | [`.cursor/skills/integrate-tokenops/SKILL.md`](../../.cursor/skills/integrate-tokenops/SKILL.md) |
| Architecture | [Architecture](../architecture.md) · [Run attribution](../run-attribution.md) |

---

## Mental model

- **Govern the run, not the request.** One `run_id` spans every LLM call, tool, and agent hop in a workflow.
- **Two layers.** The **control plane** registers runs and holds shared SQLite (budgets, policies, ledger). The **SDK** in each agent process enforces at crossings (`wrap_complete`, Chronicle hook).
- **`tokenops_run` is register-or-join.** Entry opens a new run; downstream hops with `X-TokenOps-Run-Id` join the same run. Same API either way.
- **`wrap_complete` is in-path.** Detect → decide → apply runs *before* the next model call (halt, mutate, inject), not as post-hoc analytics.
- **One shared ledger.** Child spend hits that ledger once — **no parent cost rollup**. Do not re-bill delegated work on the parent.

TokenOps does **not** own your agent loop, HTTP framework, or protocol. You keep your runtime; you point LLM (and optionally tool) crossings through the SDK.

Chronicle records decision boundaries; TokenOps observes them for cost/governance. See [Chronicle](https://github.com/theagentplane/chronicle).

---

## Prerequisites

| Need | Notes |
|------|--------|
| **Python 3.10+** | Required |
| **`pip install agent-tokenops`** | Import is still `tokenops`. Pulls Chronicle ≥0.1.3, FastAPI, httpx, provider clients, etc. |
| **Control plane + shared DB** *(multi-process)* | `TOKENOPS_URL` (e.g. `http://localhost:7700`) and `TOKENOPS_DB` shared by plane + agents. Seed governance once (`make db-reset`). |
| **Or embedded Store** *(single-process / tests)* | Omit `TOKENOPS_URL` or set `TOKENOPS_EMBEDDED=1`. |
| **LLM API keys** | Only for real model calls — not required for TokenOps itself or offline tests. |
| **FastAPI** | Optional. Only if you use `instrument_app`. Otherwise pass kwargs / `RequestContext` to `tokenops_run`. |
| **Chronicle `@boundary`** | Optional. Only if tools should be governed; LLM-only stacks can stop at `wrap_complete`. |

You do **not** need A2A, LangChain, an `agent.run` method, or the Admin UI for governance to work.

---

## Platform integrate (required)

Four steps. Everything else is optional wiring for a specific host.

### 1. Point at a plane (or embed)

```bash
# Multi-process
export TOKENOPS_URL=http://localhost:7700
export TOKENOPS_DB=tokenops.db
make db-reset          # seed budgets/policies once
make control-plane     # :7700

# Or single-process / tests
export TOKENOPS_EMBEDDED=1
```

```python
from tokenops import ControlPlaneClient

client = ControlPlaneClient.from_env()
```

### 2. Open a run per workflow

```python
from tokenops import tokenops_run

with tokenops_run(
    client=client,
    headers=incoming_headers,   # may include X-TokenOps-Run-Id
    payload=payload,            # work payload (e.g. {"task": "..."})
    service="myagent",
    intent="my_intent",         # agent-owned attribution
) as bound:
    ...
```

- **No run header** → registers a new run.
- **`X-TokenOps-Run-Id` present** → joins that run (downstream hop).

FastAPI convenience: call `instrument_app(app, service=..., intent=..., ...)` once so middleware fills `RequestContext`, then `with tokenops_run(client=client) as bound:` with fewer kwargs. Non-FastAPI: pass kwargs (above) or `bind_request_context(RequestContext(...))`.

Use `bound.governor`, `bound.controls`, `bound.attr` — do not hand-roll attribution.

### 3. Wrap every LLM completion

```python
from tokenops.control import wrap_complete
from tokenops.providers import complete  # or your own dispatch

governed = wrap_complete(
    bound.governor,
    bound.controls,
    bound.attr,
    provider="openai",
    model="gpt-4o-mini",
    dispatch=complete,       # callable(provider, model, messages, ...) -> ModelResponse
    service="myagent",
)

# Call governed instead of your raw complete / chat.completions.create
resp = governed("openai", "gpt-4o-mini", messages)
```

Your agent framework does not matter. Inject `governed` wherever you would have called the model (callback, tool-node, LangChain LLM wrapper, plain function). There is **no** required `agent.run` API.

Policies may raise `Halt` / `Throttled` from TokenOps — catch and map them however your product wants (HTTP status, structured error, retry). See appendix for the optional HTTP helper used in demos.

### 4. Multi-agent: propagate the run id

On every hop to another agent, forward:

- `X-TokenOps-Run-Id`
- parent span header when you have one (`X-TokenOps-Parent-Span-Id`)

Downstream processes use the **same** `tokenops_run` + `wrap_complete` pattern; they join, they do not mint a new run.

---

## Optional (not required for governance)

| Piece | What it is |
|-------|------------|
| `instrument_app` | FastAPI middleware: bind `RequestContext` + install Chronicle crossing hook |
| Chronicle `@boundary` | Mark tool/function crossings so the hook can observe them |
| `with_governance_errors` | Maps `Halt` → HTTP 200 halted / `Throttled` → 429 for **HTTP task handlers** — convenience, not core |
| Admin / Dashboard UI | Operate budgets and inspect runs — not on the enforcement path |
| In-repo demos | Illustrate one host shape (A2A + injectable `complete_fn`) |

---

## FAQ

### Do I need `agent.run` or a specific agent object?

No. That pattern is only how **our example agents** accept an injectable completion function. Your code can call `governed(...)` directly, pass it into LangGraph/Crew/etc., or wrap a vendor SDK — TokenOps does not prescribe a method name.

### Do I need `create_a2a_app`?

No. That helper lives under `examples/` for the A2A benches. TokenOps talks to FastAPI via `instrument_app` if you use FastAPI; otherwise you call `tokenops_run` with explicit context.

### What is `with_governance_errors`?

An optional HTTP wrapper in `tokenops.control.http` so demo task handlers return JSON instead of 500 when a policy raises `Halt` or `Throttled`. Production apps often map those exceptions themselves. Governance works without it.

### Why do I pass `provider` / `model` to `instrument_app`?

They are **defaults** for crossings that do not carry their own (typical for some tool boundaries). LLM calls already pass provider/model on `wrap_complete`. Empty defaults are fine for LLM-only setups.

### Entry vs downstream — different APIs?

No. Both use `with tokenops_run(...) as bound:`. Entry registers when there is no run header; downstream joins via `X-TokenOps-Run-Id`.

### Who owns `intent` / governance `mode`?

The **integrating agent** (kwargs to `instrument_app` / `tokenops_run`), not the client UI. Callers should send **work** (e.g. task text). Optional caller identity (e.g. `user_id`) may still merge from the payload under allow-listed rules.

### When do I need Chronicle `@boundary`?

When tools should appear on the ledger / be governed. Without `@boundary` + the crossing hook, TokenOps only sees LLM calls you put through `wrap_complete`.

### Embedded Store vs `TOKENOPS_URL`?

| Mode | When |
|------|------|
| `TOKENOPS_URL` set | Multi-process: register via HTTP; share `TOKENOPS_DB` with the plane. Agents must **not** mount `/v1/runs`. |
| `TOKENOPS_EMBEDDED=1` or no URL | Tests / single process: in-process `Store`. |

### Do I construct `Store(...)` in the agent?

Prefer `ControlPlaneClient.from_env()` and `tokenops_run`. Happy path does not require user-facing `Store(...)` construction.

---

## Appendix: example bench shape (not the platform)

In-repo demos (`examples/agents/`, `examples/triad/`) use a **local** convention:

1. Build an HTTP app with `examples.a2a.server.create_a2a_app(..., handler=...)`.
2. Wrap the handler with `with_governance_errors` so `Halt`/`Throttled` become HTTP responses.
3. Keep agent logic in a plain class with `run(..., complete_fn=...)` so the server can inject `wrap_complete`.

That is **one** way to host TokenOps — useful for reading the field guide — not a requirement for integrators. Prefer the [Platform integrate](#platform-integrate-required) section above.

Deep dive on that bench: [Field guide](field-guide-add-tokenops.md).

---

## What TokenOps is not doing today

TokenOps is **0.x / draft**. Honest limits (details: [control-plane status](../control-plane-status.md); high-level: [README Roadmap](../../README.md#roadmap)):

- **Not a full remote observe/decide plane yet.** Agents still enforce in-process with a shared SQLite ledger; register is remote when `TOKENOPS_URL` is set.
- **Not a prescribed agent framework.** No required `agent.run`, A2A stack, or LangChain. You wire crossings.
- **Not automatic for arbitrary HTTP frameworks.** FastAPI gets `instrument_app`; others pass context into `tokenops_run` yourself.
- **Not automatic tool wrapping.** Tools need Chronicle `@boundary` (hook installed by `instrument_app` / `tokenops.init`).
- **Not per-user / tag budget seed by default.** Seeded governance is **run-scoped** today; segment-scoped budgets are WIP.
- **Not parent rollup of child spend.** By design: one ledger, one booking.
- **Not production-hardened multi-host without shared storage.** Cross-process correctness assumes shared `TOKENOPS_DB` (or a future remote ledger). See [concurrency](../concurrency.md).

What **is** working today: run registration, `tokenops_run` + `wrap_complete`, shared ledger halt/spend, seeded policies, Admin/Dashboard, and illustrative demos under `examples/`.
