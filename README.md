<div align="center">

# TokenOps

**One budget for a whole agent workflow, enforced before each call.**<br>
Your agent stops when the run is out of money, instead of after the bill arrives.

[![CI](https://github.com/theagentplane/tokenops/actions/workflows/ci.yml/badge.svg)](https://github.com/theagentplane/tokenops/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/agent-tokenops.svg)](https://pypi.org/project/agent-tokenops/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://pypi.org/project/agent-tokenops/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE.txt)

<sub>Featured by <a href="https://www.linkedin.com/posts/microsoft-developers_who-spent-all-the-tokens-tokenops-gives-activity-7499191980715982848-224b">Microsoft Developer</a> · <a href="https://commandline.microsoft.com/tokenops-real-time-run-scoped-cost-control-ai-agents/">Command Line</a> · <a href="https://www.youtube.com/watch?v=GJX19pNhmSw">AI Engineer World's Fair</a></sub>

<br>

Built by <b><a href="https://www.linkedin.com/in/susheemkoul/">Susheem Koul</a></b> and <b><a href="https://www.linkedin.com/in/tisha-chawla/">Tisha Chawla</a></b>

<a href="https://github.com/theagentplane/tokenops/raw/main/examples/demo-assets/videos/02_governance_on_budget_cap.webm">
<img src="https://raw.githubusercontent.com/theagentplane/tokenops/main/examples/demo-assets/videos/02_governance_on_budget_cap.gif" alt="TokenOps demo: a governed Research to Summarize run halts when worst-case cost exceeds the remaining run budget, then the Dashboard shows spend and governance per agent" width="720" />
</a>

<sub><i>Governed Research → Summarize run: the budget cap halts spend mid-run, then the Dashboard attributes cost per agent. <a href="https://github.com/theagentplane/tokenops/raw/main/examples/demo-assets/videos/02_governance_on_budget_cap.webm">Full video</a>.</i></sub>

</div>

<br>

## Start here

### 1. See it work

```bash
pip install agent-tokenops
python -m tokenops.demo
```

No API keys, no server, no Docker. It runs the same agent loop twice:

```
An agent makes 40 model calls. Budget for the whole run: $2.00.

  without TokenOps   40 calls run, spend $5.80
  with TokenOps      halted at call 12, spend $2.03

  $3.77 not spent. The run stopped itself.
```

No single call was expensive. Together they crossed the cap, which is what a
per-request limit cannot see.

### 2. Put it in your agent

**The fastest way is to let your coding assistant do it.** TokenOps ships an
integration skill: a written procedure your assistant reads and follows. It reads
your agent, picks the right setup, wires the enforcement point, and tells you what
to check.

In **Claude Code**, from a clone:

```
/integrate-tokenops
```

In **Cursor, Copilot, or anywhere else**, paste this:

> Integrate TokenOps into this agent, following
> https://github.com/theagentplane/tokenops/blob/main/.claude/skills/integrate-tokenops/SKILL.md

The skill handles three setups: one process, several processes sharing one budget,
or FastAPI and A2A services. It is
[`.claude/skills/integrate-tokenops/SKILL.md`](.claude/skills/integrate-tokenops/SKILL.md),
plain markdown, readable on its own if you would rather follow it yourself.

<details>
<summary><b>Or wire it yourself</b>, about ten lines</summary>

<br>

Wrap your model call once, then hand the wrapped version to your agent.

```python
from tokenops import ControlPlaneClient, tokenops_run
from tokenops.control import Halt, wrap_complete
from tokenops.providers import complete

client = ControlPlaneClient.from_env()

with tokenops_run(client=client, service="my-agent", intent="research",
                  provider="openai", model="gpt-4o") as bound:
    governed = wrap_complete(
        bound.governor, bound.controls, bound.attr,
        provider="openai", model="gpt-4o",
        dispatch=complete, service="my-agent",
    )
    try:
        agent.run(..., complete_fn=governed)   # <-- pass `governed`, not `complete`
    except Halt as stopped:
        print(f"run stopped: {stopped}")
```

**The only change to your agent is that one line.** If your agent hard-codes its
model client, make the completion function injectable. Nothing else moves.

`wrap_complete` checks the budget before each call and records the cost after.
When the run runs out, it raises `Halt`, and later calls on that run are refused,
even from another process.

</details>

### 3. When you need more

| You want to | Go to |
|---|---|
| Change the budget from $2.00 | [Set the budget](.claude/skills/integrate-tokenops/SKILL.md#set-the-budget) |
| One budget across several agent processes | [Shared plane](.claude/skills/integrate-tokenops/SKILL.md#tier-2--several-processes-one-budget) |
| FastAPI or A2A services | [Instrumented app](.claude/skills/integrate-tokenops/SKILL.md#tier-3--fastapi--a2a) |
| Something other than stopping | [The ten policies](docs/policies/) |
| Cost per agent in a dashboard | [Run it locally](#run-it-locally) |
| A worked end-to-end example | [Field guide](docs/guides/field-guide-add-tokenops.md) |
| Everything else | [Onboarding guide](docs/guides/onboarding.md) |


## Why TokenOps

**The problem.** Your agent workflow calls a model twenty times. Each call is
cheap and each one passes whatever per-request limit you set. The workflow still
costs ten times what you expected, and nothing stopped it, because nothing was
counting the workflow as one thing.

**What TokenOps does.** It gives the whole workflow one budget and one running
total, and it checks that total *before* each call rather than reporting on it
afterwards. Cross the budget and the run stops.

A few things follow from that:

- **It works across processes.** Research, summarize and review can be three
  separate services and still share one budget. Without that, each one gets the
  full cap and you pay three times over.
- **Stopping is not the only option.** A policy can also shrink the next prompt,
  swap to a cheaper model, or tell the agent it is going in circles. Stopping is
  the last resort, not the only tool.
- **Tool calls count too.** Not just model calls. Search results and file reads
  end up in the next prompt, and that is real spend.
- **It is not a dashboard.** Analytics tell you what you already spent. This
  refuses the call that would break the budget.

Ten policies ship configured. You can [add your own](docs/policies/).

## How TokenOps compares

TokenOps is not a gateway or a tracing dashboard. It governs the **run**, a full agent workflow, and sits alongside the tools you already use for routing and observability.

| | TokenOps | LiteLLM / Portkey / AI Gateway | Langfuse |
|---|:---:|:---:|:---:|
| Primary focus | Run (stateful) | Request | Trace (observe) |
| Multi-agent workflow as one unit | Yes | No | Manual stitch |
| Budget enforcement in-path | Yes (run-aware) | Yes (key/team) | No (analytics) |
| Steer next call (mutate / inject) | Yes | Routing / fallbacks | No |
| Shared ledger across agent processes | Yes | N/A | N/A |

What this does **not** do: replace your LLM gateway, replace Chronicle-style record-and-replay, or host a SaaS control plane for you.

Longer table with logos: [`docs/product/comparison.md`](docs/product/comparison.md).

## Run it locally

Only needed if you want the dashboard, the multi-agent benches, or a budget shared
across processes. Step 1 needs none of this.

```bash
git clone https://github.com/theagentplane/tokenops && cd tokenops
make install
make run          # control plane :7700 + Admin/Dashboard :8501
```

Then open `localhost:8501` to see spend and governance per agent.

<details>
<summary><b>Multi-agent benches</b>: watch one budget span several agents</summary>

<br>

Each is a real multi-agent stack sharing one run ledger. One target starts the
plane, the agents, and the Admin UI.

| Bench | Agents | Run |
|---|---|---|
| Two-agent | Research to Summarize | `make demo` |
| Triad | Planner to Researcher to Writer | `make demo-triad` |
| Brief | Scout to Analyst to Editor (LangChain) | `make demo-brief` |
| Bench UI | Chat + Simulator only | `make bench-ui` |

`cp .env.example .env` first if you want them to call real models.

Docker instead of make: `docker compose up --build`. See
[`docs/control-plane-deploy.md`](docs/control-plane-deploy.md) for the UI and
two-agent profiles, and [`examples/README.md`](examples/README.md) for the benches.

</details>

<details>
<summary><b>Pointing several processes at one plane</b></summary>

<br>

```bash
export TOKENOPS_URL=http://localhost:7700
export TOKENOPS_DB=tokenops.db   # plane and every agent read the same file
```

> `TOKENOPS_EMBEDDED=1` overrides `TOKENOPS_URL`. Leave it unset here, or each
> process silently falls back to its own local ledger and gets the full budget.

PyPI name is `agent-tokenops`; the import is `tokenops`. Extras:
`pip install "agent-tokenops[examples]"` for the LangChain benches,
`".[dev,examples]"` from source. Releases: [`RELEASING.md`](RELEASING.md).

</details>

## Reference

Things you will want eventually, not now.

<details>
<summary><b>Architecture: how the plane and the SDK split the work</b></summary>

TokenOps is two layers that share one artifact, the **run**: a control plane that registers runs and stores budgets/policies, and an in-process SDK that enforces at every boundary crossing.

```mermaid
flowchart LR
    subgraph PLANE["Control plane (:7700)"]
        R["POST /v1/runs"] --> DB[("SQLite TOKENOPS_DB<br/>registrations · budgets · policies · ledger")]
        UI["Admin + Dashboard"] --> DB
    end

    subgraph AGENTS["Agent processes (SDK)"]
        E["Entry agent<br/>tokenops_run"] -->|"register_run"| R
        E -->|"X-TokenOps-Run-Id"| D["Downstream agents<br/>tokenops_run"]
        E & D -->|"wrap_complete"| G["Governor<br/>pre_call → detect → decide → apply"]
        E & D -->|"@boundary + crossing hook"| G
        G --> L["Shared ledger<br/>(same run_id)"]
    end

    L --> DB
    DB -->|"governance_config_for"| G
```

| Piece | Owns | Does not own |
|---|---|---|
| **Control plane** (`python -m tokenops.server`) | `POST /v1/runs`, shared SQLite, Admin/Dashboard | Agent loops, LLM calls, tools |
| **SDK (in agents)** | `tokenops_run`, `wrap_complete`, ledger/policies, Chronicle crossing hook | Ad-hoc run IDs; mounting `/v1/runs` when `TOKENOPS_URL` is set |

Chronicle records decision boundaries; TokenOps attaches as the cost/governance observer on live crossings. See [Chronicle](https://github.com/theagentplane/chronicle) for record-and-replay.

</details>

<details>
<summary><b>Environment variables</b></summary>

| Variable | Purpose |
|---|---|
| `TOKENOPS_URL` | Remote plane base URL (e.g. `http://localhost:7700`) → HTTP `register_run` |
| `TOKENOPS_EMBEDDED` | Set to `1` to force in-process `Store` (tests / single-process) |
| `TOKENOPS_DB` | SQLite path shared by plane + agents |
| `TOKENOPS_CONFIG` | YAML for governance seed (core: `src/tokenops/config/default.yaml`) |

`TOKENOPS_URL` also accepts the aliases `CONTROL_PLANE_URL` and
`TOKENOPS_CONTROL_PLANE_URL`.

Production / multi-process: set `TOKENOPS_URL`; agents must **not** mount `/v1/runs`. Tests: `TOKENOPS_EMBEDDED=1` (or omit URL).

> **Precedence.** `ControlPlaneClient.from_env` takes the HTTP path only when a
> URL is set **and** `TOKENOPS_EMBEDDED` is not `1`. Setting both falls back to a
> local SQLite file with no warning, and every process then gets its own full
> budget. Check with
> `print("embedded" if client.embedded else client.url)`.

</details>

<details>
<summary><b>Make targets</b></summary>

| Target | Role |
|--------|------|
| `make install` | Editable install with dev + examples extras |
| `make dist` / `check-dist` | Build sdist+wheel / `twine check` |
| `make control-plane` | Standalone plane (`python -m tokenops.server`) on `:7700` |
| `make ui` | Admin + Dashboard on `:8501` |
| `make run` | Plane + Admin/Dashboard |
| `make demo-quick` | `python -m tokenops.demo`: no API keys, no server |
| `make demo` / `demo-triad` / `demo-brief` | Runnable A2A stacks |
| `make bench-ui` | Chat + Simulator |
| `make db-reset` | Clear SQLite + reseed from `TOKENOPS_CONFIG` |
| `make stop` | Kill listeners on `:7700` / `:8501` |
| `make sync-skills` | Regenerate the editor copies of the integration skill |

</details>

<details>
<summary><b>Project structure</b></summary>

Only `src/tokenops/` is the installable package. Demos and benches stay under `examples/`.

```
src/tokenops/              # installable package
├── server/                # control plane (:7700, POST /v1/runs)
├── control/               # SDK: ledger, policies, wrap_complete, crossing hook
├── providers/             # OpenAI / Anthropic complete dispatch
├── config/                # default.yaml governance seed
└── ui/                    # Admin + Dashboard (Streamlit)
examples/                  # A2A benches (two-agent, triad, brief) + Chat/Simulator
benchmarking/              # MetaGPT / browser-use live harness
docs/                      # architecture, policies, guides, product
tests/                     # unit + e2e
```

</details>

<details>
<summary><b>More documentation</b></summary>

- [Onboarding](docs/guides/onboarding.md): prereqs, minimum integration, FAQ, current limits
- [Field guide](docs/guides/field-guide-add-tokenops.md): a triad walked through, with screenshots
- [Policies](docs/policies/): one page per policy
- [Run attribution](docs/run-attribution.md) - [control plane deploy](docs/control-plane-deploy.md) - [status](docs/control-plane-status.md)
- [Examples](examples/README.md) - [comparison](docs/product/comparison.md) - [shared ledger](docs/product/shared-ledger.md)

</details>

## Roadmap

TokenOps is early (0.x). Near-term:

- User/tag segment-scoped budgets (machinery exists; seed is run-only today).
- Optional fail-closed integrity: refuse on missing registration or exceeded budget.
- Remote observe / decide (fatter plane) for multi-host stacks.
- Documentation site.

Status of each control-plane job: [`docs/control-plane-status.md`](docs/control-plane-status.md).

## Talks & press

- **Featured by Microsoft Developer**: “Who spent all the tokens?” on
  [LinkedIn](https://www.linkedin.com/posts/microsoft-developers_who-spent-all-the-tokens-tokenops-gives-activity-7499191980715982848-224b) and [X](https://x.com/msdev/status/2093425027500978292).
- **[Who spent all the tokens? Real-time, run-scoped cost control for AI agents](https://commandline.microsoft.com/tokenops-real-time-run-scoped-cost-control-ai-agents/)**: *Command Line*, a Microsoft publication. Why per-request caps miss agent workflows, and how a run-scoped ledger plus in-path enforcement stops the bill mid-run.
- **[FinOps for AI Agents: Who Spent All the Tokens?](https://www.youtube.com/watch?v=GJX19pNhmSw)**: talk at the **AI Engineer World's Fair**, San Francisco. Live walkthrough of a governed multi-agent run hitting its budget cap.

## Community

**[Join The Agent Plane on Slack](https://join.slack.com/t/theagentplane/shared_invite/zt-47lqx2xtc-0idr1cuLNJ_JDTgqxDiUsg)**
for real-time questions, integration help, and demos of what you have governed.

For longer-form questions, ideas, and show-and-tell, use
[GitHub Discussions](https://github.com/theagentplane/tokenops/discussions).

**Office hours:** if you are wiring TokenOps into a real stack and want to talk it
through, [book a slot](https://calendly.com/theagentplane/theagentplane).

**Writing, talks and videos** from the people building this, on agent
observability, replay testing, and token infrastructure:
**[theagentplane.github.io/media](https://theagentplane.github.io/media.html)**.

## Contributing

Good first contributions are labelled
[`good first issue`](https://github.com/theagentplane/tokenops/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)
and [`help wanted`](https://github.com/theagentplane/tokenops/issues?q=is%3Aissue+is%3Aopen+label%3A%22help+wanted%22).
Two areas take contributions without touching the core:

- **A new policy** (a detector plus a decision) under `src/tokenops/control/policies/`.
  Ten existing ones are working references, one doc each in [`docs/policies/`](docs/policies/).
- **A new adapter** so another SDK can be governed, under `src/tokenops/adapters/`.

Bugs belong in Issues. Open an issue before a pull request so the approach can
be agreed there first; typos and small docs fixes can go straight to a PR. See
[CONTRIBUTING.md](CONTRIBUTING.md), [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md),
and [SECURITY.md](SECURITY.md).

```bash
make install
make lint
make test
```

## Contributors

Thanks to everyone who has contributed.

[![Contributors](https://contrib.rocks/image?repo=theagentplane/tokenops)](https://github.com/theagentplane/tokenops/graphs/contributors)

---

If TokenOps saves you a runaway agent bill, please [⭐ star the repo](https://github.com/theagentplane/tokenops) so more people can find it.

<div align="center">

[Slack](https://join.slack.com/t/theagentplane/shared_invite/zt-47lqx2xtc-0idr1cuLNJ_JDTgqxDiUsg) · [Discussions](https://github.com/theagentplane/tokenops/discussions) · [PyPI](https://pypi.org/project/agent-tokenops/)

</div>
