# Demo bench walkthrough

The reference **two-agent test bench** demonstrates TokenOps on a research → summarize pipeline.
Runnable code lives under [`examples/`](../../examples/).

```bash
make install
make demo          # plane + research + summarize + Admin UI
make bench-ui      # Chat + Simulator (screenshots below)
```

Screenshots below are from the local Streamlit UI shipped with the demo harness (`examples/ui`).

## Pages

| Page | Purpose |
|---|---|
| **Test Bench** | Live pipeline — research agent delegates to summarize over HTTP |
| **Run simulator** | In-process run with live timeline, trace, and control-plane tabs |
| **Policy admin** | Edit budgets, policies, and segments (plane Admin UI) |
| **Dashboard** | Run history, aggregate cost, problematic runs |

---

## 1. Test Bench — trigger a live run

Configure task, corpus profile, and agent endpoints in the sidebar. Click **Run pipeline** to send a task to the research agent, which delegates to summarize.

![Test Bench](../assets/screenshots/01-test-bench.png)

---

## 2. Run simulator — in-process demo (no API keys required)

**Demo mode** uses a stub LLM so you can explore governance without provider credentials. Click **Start run** to execute research → summarize in one process.

![Simulator start](../assets/screenshots/02-simulator-start.png)

### Live timeline

The timeline shows LLM / tool steps, spend, and control actions (HALT, MUTATE, …) as they fire.

![Simulator timeline during run](../assets/screenshots/05-simulator-halted.png)

### Control-plane tab

Spend and policy trips for the run.

![Control plane view](../assets/screenshots/06-simulator-control-plane.png)

---

## 3. Policy admin — budgets and policies

Edit run budgets and policy params. Changes apply on the next run (no restart).

![Policy admin — budgets](../assets/screenshots/03-admin-budgets.png)

![Policy admin — policies](../assets/screenshots/03b-admin-policies.png)

---

## 4. Dashboard — history and cost

![Dashboard](../assets/screenshots/04-dashboard.png)

---

## Shared ledger across agents

→ Full walkthrough with screenshots: [Shared ledger](./shared-ledger.md)

[Back to overview](../../README.md) · [Shared ledger](./shared-ledger.md) · [Policies](../policies/)
