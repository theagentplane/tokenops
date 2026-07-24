# Onboarding: TokenOps in five minutes of concepts

New to TokenOps? Start here. This page covers the mental model, prerequisites,
bare-minimum integration, FAQ, and what TokenOps is **not** doing today.

| Go deeper | Doc |
|-----------|-----|
| Triad walkthrough + screenshots | [Field guide](field-guide-add-tokenops.md) |
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

Chronicle records decision boundaries; TokenOps observes them for cost/governance. See [Chronicle](https://github.com/theagentplane/chronicle).

---

## Prerequisites

| Need | Notes |
|------|--------|
| **Python 3.10+** | Required |
| **`pip install agent-tokenops`** | Import is still `tokenops`. Pulls Chronicle ≥0.2.0, FastAPI, httpx, provider clients, etc. |
| **Control plane + shared DB** *(multi-process)* | `TOKENOPS_URL` (e.g. `http://localhost:7700`) and `TOKENOPS_DB` shared by plane + agents. Seed governance once (`make db-reset`). |
| **Or embedded Store** *(single-process / tests)* | Omit `TOKENOPS_URL` or set `TOKENOPS_EMBEDDED=1`. |
| **LLM API keys** | Only for real model calls — not required for TokenOps itself or offline tests. |
| **FastAPI** | Only if you use `instrument_app`. Non-FastAPI: pass kwargs / `RequestContext` to `tokenops_run`. |
| **Chronicle `@boundary`** | Only if tools should be governed; LLM-only stacks can stop at `wrap_complete`. |

You do **not** need A2A, `create_a2a_app`, LangChain, or the Admin UI for governance to work.

---

## Bare-minimum integrate

### 1. Start the plane (multi-process)

```bash
export TOKENOPS_URL=http://localhost:7700
export TOKENOPS_DB=tokenops.db
make db-reset          # seed budgets/policies once
make control-plane     # :7700
```

### 2. Instrument the app once (FastAPI)

```python
from tokenops import ControlPlaneClient, instrument_app, tokenops_run
from tokenops.control import wrap_complete, with_governance_errors
from tokenops.providers import complete

client = ControlPlaneClient.from_env()

# After you build your FastAPI app (A2A helper or otherwise):
instrument_app(
    app,
    service="myagent",
    intent="my_intent",          # agent-owned; UI sends task only
    provider="openai",           # defaults for crossings without their own
    model="gpt-4o-mini",
)
```

`instrument_app` only needs a FastAPI `app`. It does **not** assume `create_a2a_app`.

### 3. Per request: open the run + wrap the LLM

```python
async def handler(payload: dict, headers: Mapping[str, str]) -> dict:
    with tokenops_run(client=client) as bound:
        governed = wrap_complete(
            bound.governor, bound.controls, bound.attr,
            provider="openai", model="gpt-4o-mini",
            dispatch=complete, service="myagent",
        )
        return agent.run(..., complete_fn=governed)

app = create_a2a_app(..., handler=with_governance_errors(handler))
# then instrument_app(app, ...)
```

Use `bound.*` from `tokenops_run` — do not hand-roll attribution or a separate governance scope.

### 4. Multi-agent: propagate the run

Forward `X-TokenOps-Run-Id` (and parent span when you have one) on every hop.
A2A `post_task` merges ambient headers when you are already inside `tokenops_run`.
Downstream agents use the **same** `tokenops_run` + `wrap_complete` pattern; they join, they do not mint a new run.

### Non-FastAPI

```python
from tokenops import RequestContext, bind_request_context, tokenops_run

bind_request_context(RequestContext(
    headers=dict(headers), payload=payload, service="myagent", intent="my_intent",
))
with tokenops_run(client=client) as bound:
    ...
```

Or pass `headers=`, `payload=`, `service=`, `intent=` explicitly to `tokenops_run(...)`.

---

## FAQ

### Why do I pass `provider` / `model` to `instrument_app`?

They are **agent defaults** stored on `RequestContext`, then copied into the governance scope as a **fallback** when a crossing does not carry its own provider/model (typical for Chronicle **tool** boundaries). LLM calls already pass provider/model on `wrap_complete`, so empty defaults are fine for LLM-only setups.

### Does `instrument_app` require A2A or `create_a2a_app`?

No. It registers FastAPI HTTP middleware + installs the Chronicle crossing hook. Any FastAPI app works. `create_a2a_app` is only the demo/A2A helper that builds that app.

### Entry vs downstream — different APIs?

No. Both use `with tokenops_run(...) as bound:`. Entry registers when there is no run header; downstream joins via `X-TokenOps-Run-Id`.

### Who owns `intent` / governance `mode`?

The **agent** (via `instrument_app` / `tokenops_run` kwargs), not the UI. Clients should send **task only**. Optional caller identity (e.g. `user_id`) may still flow from the payload under allow-listed merge rules.

### When do I need Chronicle `@boundary`?

When tools (search, fetch, etc.) should appear on the ledger / be governed. Without `@boundary` + the crossing hook, TokenOps only sees LLM calls you put through `wrap_complete`.

### Embedded Store vs `TOKENOPS_URL`?

| Mode | When |
|------|------|
| `TOKENOPS_URL` set | Production / multi-process: register via HTTP; share `TOKENOPS_DB` with the plane. Agents must **not** mount `/v1/runs`. |
| `TOKENOPS_EMBEDDED=1` or no URL | Tests / single process: in-process `Store`. |

### Do I construct `Store(...)` in the agent?

Prefer `ControlPlaneClient.from_env()` and `tokenops_run`. Happy path does not require user-facing `Store(...)` construction.

### Tools usually cost $0 — why govern them?

Ledger cost may be zero, but policies still care about steps, concurrency, tool frequency, output size, and progress. Spend is one dimension among several.

---

## What TokenOps is not doing today

TokenOps is **0.x / draft**. Honest limits (details and status matrix: [control-plane status](../control-plane-status.md); high-level plan: [README Roadmap](../../README.md#roadmap)):

- **Not a full remote observe/decide plane yet.** Agents still enforce in-process with a shared SQLite ledger; register is remote when `TOKENOPS_URL` is set. A fatter plane (remote observe/decide) is on the roadmap.
- **Not automatic for arbitrary frameworks.** FastAPI gets `instrument_app`; other stacks wire `tokenops_run` / `RequestContext` yourself — no Flask/Django/etc. middleware ships today.
- **Not automatic tool wrapping.** Tools are not governed unless you use Chronicle `@boundary` (and the crossing hook, installed by `instrument_app` / `tokenops.init`).
- **Not per-user / tag budget seed by default.** Registration stores `user_dims`, but seeded governance is **run-scoped** today; segment-scoped budgets are WIP.
- **Not parent rollup of child spend.** By design: one ledger, one booking. Do not double-count delegated work on the parent.
- **Not a replacement for your agent runtime.** TokenOps does not own prompts, planners, or tool loops — it governs crossings you expose.
- **Not production-hardened multi-host without shared storage.** Cross-process correctness assumes a shared `TOKENOPS_DB` (or future remote ledger). See also [concurrency](../concurrency.md).

What **is** working today for the happy path: run registration, `tokenops_run` + `wrap_complete`, shared ledger halt/spend, seeded policies, Admin/Dashboard, and the in-repo demos (`make demo` / `demo-triad` / `demo-brief`).
