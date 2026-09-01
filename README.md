<div align="center">

# TokenOps

**Run-aware token governance for multi-agent systems.**<br>
Cap spend and steer behavior across a whole agent workflow, not per request, with a shared ledger and in-path enforcement.

<sub>Built by <b>Susheem Koul</b> and <b>Tisha Chawla</b></sub>

[![CI](https://github.com/theagentplane/tokenops/actions/workflows/ci.yml/badge.svg)](https://github.com/theagentplane/tokenops/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/agent-tokenops.svg)](https://pypi.org/project/agent-tokenops/)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://github.com/theagentplane/tokenops)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE.txt)
[![Status](https://img.shields.io/badge/status-0.x%20%7C%20draft-7B61FF?style=flat-square)](https://semver.org/)
[![Stars](https://img.shields.io/github/stars/theagentplane/tokenops?style=flat&color=yellow)](https://github.com/theagentplane/tokenops/stargazers)
[![Discussions](https://img.shields.io/badge/GitHub-Discussions-7B61FF?style=flat)](https://github.com/theagentplane/tokenops/discussions)
[![Slack](https://img.shields.io/badge/Slack-join%20the%20community-4A154B?style=flat&logo=slack&logoColor=white)](https://join.slack.com/t/theagentplane/shared_invite/zt-47lqx2xtc-0idr1cuLNJ_JDTgqxDiUsg)

[![Featured by Microsoft Developer](https://img.shields.io/badge/Featured%20by-Microsoft%20Developer-0078D4?style=flat&logo=microsoft&logoColor=white)](https://www.linkedin.com/posts/microsoft-developers_who-spent-all-the-tokens-tokenops-gives-activity-7499191980715982848-224b)
[![Command Line, a Microsoft publication](https://img.shields.io/badge/Command%20Line-Microsoft-5E5E5E?style=flat&logo=microsoft&logoColor=white)](https://commandline.microsoft.com/tokenops-real-time-run-scoped-cost-control-ai-agents/)
[![Talk: AI Engineer World's Fair](https://img.shields.io/badge/Talk-AI%20Engineer%20World%27s%20Fair-FF0000?style=flat&logo=youtube&logoColor=white)](https://www.youtube.com/watch?v=GJX19pNhmSw)

<br>

<a href="https://github.com/theagentplane/tokenops/raw/main/examples/demo-assets/videos/02_governance_on_budget_cap.webm">
<img src="https://raw.githubusercontent.com/theagentplane/tokenops/main/examples/demo-assets/videos/02_governance_on_budget_cap.gif" alt="TokenOps demo: a governed Research to Summarize run halts when worst-case cost exceeds the remaining run budget, then the Dashboard shows spend and governance per agent" width="720" />
</a>

<sub><i>Governed Research → Summarize run: the budget cap halts spend mid-run, then the Dashboard attributes cost per agent. <a href="https://github.com/theagentplane/tokenops/raw/main/examples/demo-assets/videos/02_governance_on_budget_cap.webm">Full video</a>.</i></sub>

</div>

<br>

TokenOps is a **control plane + SDK** for agent stacks. Entry agents register a run; every LLM and tool crossing shares one `run_id` and one ledger. Policies can halt, mutate, or inject before the next call executes, so a research → summarize → review pipeline stays inside a single budget even across processes.

**[Why](#why-tokenops) · [Architecture](#architecture) · [Install](#install) · [Quick start](#quick-start) · [Demos](#demos) · [Comparison](#how-tokenops-compares) · [Roadmap](#roadmap) · [Talks & press](#talks--press) · [Community](#community)**

## Why TokenOps

- **Govern the run, not the request.** One `run_id` spans every model, tool, and A2A hop in a workflow.
- **Shared ledger across processes.** Spend, inflight, and halt live in SQLite so multi-agent stacks cannot each burn the full cap locally.
- **In-path enforcement.** `wrap_complete` runs detect → decide → apply *before* the next LLM call; Chronicle `@boundary` + a crossing hook ingest tool spend.
- **Steer or stop.** Actuators: `HALT` · `MUTATE` · `INJECT` · reject/queue, not just post-hoc analytics.
- **Batteries included.** Control plane (`:7700`), Admin + Dashboard UI, ten seeded policies, and runnable A2A benches (two-agent, triad, LangChain brief).

## Architecture

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

## Install

```bash
pip install agent-tokenops

# With example / bench extras (LangChain, ddgs):
pip install "agent-tokenops[examples]"

# From source (development):
pip install -e ".[dev,examples]"
```

**Prerequisites:** Python 3.10+; `agent-tokenops`; either a running control plane
(`TOKENOPS_URL` + shared `TOKENOPS_DB`) or `TOKENOPS_EMBEDDED=1` for single-process /
tests. LLM API keys only for real model calls. FastAPI only if you use
`instrument_app`.

PyPI name is `agent-tokenops`; import is still `tokenops` (same pattern as Chronicle).
See [`RELEASING.md`](RELEASING.md) for releases.

## Quick start

```bash
make install
cp .env.example .env   # optional API keys for demos / your agents

make db-reset          # optional: clean SQLite + seed governance from default.yaml
make run               # control plane :7700 + Admin/Dashboard :8501
```

Wire governance into an agent: `instrument_app` once, then `tokenops_run` per request.
The UI sends **task only**; intent / mode come from agent config on `instrument_app`.

```python
from tokenops import ControlPlaneClient, instrument_app, tokenops_run
from tokenops.control import wrap_complete, with_governance_errors
from tokenops.providers import complete

client = ControlPlaneClient.from_env()  # TOKENOPS_URL or embedded Store

async def handler(payload: dict, headers: Mapping[str, str]) -> dict:
    with tokenops_run(client=client) as bound:
        governed = wrap_complete(
            bound.governor, bound.controls, bound.attr,
            provider=provider, model=model,
            dispatch=complete, service="planner",
        )
        run_agent(..., complete_fn=governed)

app = create_a2a_app(..., handler=with_governance_errors(handler))
instrument_app(app, service="planner", intent="triad_plan",
               provider=provider, model=model)
```

**Non-FastAPI:** TokenOps does not yet ship middleware for other frameworks. Use
`bind_request_context(RequestContext(headers=..., payload=..., service=...))` then
`with tokenops_run():`, or pass those kwargs explicitly to `tokenops_run`.

Point agents at the plane and share one DB:

```bash
export TOKENOPS_URL=http://localhost:7700
export TOKENOPS_DB=tokenops.db   # plane + all agents
make control-plane               # :7700
make ui                          # Admin + Dashboard :8501
```

New here? Start with the [onboarding guide](docs/guides/onboarding.md), then the
[integration checklist](.cursor/skills/integrate-tokenops/SKILL.md) or the
[triad field guide](docs/guides/field-guide-add-tokenops.md).

## Demos

Each bench is a multi-agent stack with a shared run ledger. Start the plane, agents, and Admin UI with one make target.

| Demo | Agents | Run |
|---|---|---|
| Two-agent | Research → Summarize | `make demo` |
| Triad | Planner → Researcher → Writer | `make demo-triad` |
| Brief | Scout → Analyst → Editor (LangChain) | `make demo-brief` |
| Bench UI | Chat + Simulator only | `make bench-ui` |

Docker:

```bash
docker compose up --build
# optional UI: docker compose --profile ui up --build
# two-agent stack:
docker compose -f docker-compose.examples.yml up --build
```

See [`examples/README.md`](examples/README.md) and [`docs/control-plane-deploy.md`](docs/control-plane-deploy.md).

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

## Make targets

<details>
<summary>Command reference</summary>

| Target | Role |
|--------|------|
| `make install` | Editable install with dev + examples extras |
| `make dist` / `check-dist` | Build sdist+wheel / `twine check` |
| `make control-plane` | Standalone plane (`python -m tokenops.server`) on `:7700` |
| `make ui` | Admin + Dashboard on `:8501` |
| `make run` | Plane + Admin/Dashboard |
| `make demo` / `demo-triad` / `demo-brief` | Runnable A2A stacks |
| `make bench-ui` | Chat + Simulator |
| `make db-reset` | Clear SQLite + reseed from `TOKENOPS_CONFIG` |
| `make stop` | Kill listeners on `:7700` / `:8501` |

</details>

## Environment variables

| Variable | Purpose |
|---|---|
| `TOKENOPS_URL` | Remote plane base URL (e.g. `http://localhost:7700`) → HTTP `register_run` |
| `TOKENOPS_EMBEDDED` | Set to `1` to force in-process `Store` (tests / single-process) |
| `TOKENOPS_DB` | SQLite path shared by plane + agents |
| `TOKENOPS_CONFIG` | YAML for governance seed (core: `src/tokenops/config/default.yaml`) |

Production / multi-process: set `TOKENOPS_URL`; agents must **not** mount `/v1/runs`. Tests: `TOKENOPS_EMBEDDED=1` (or omit URL).

## Project structure

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

## Roadmap

TokenOps is early (0.x). Near-term:

- User/tag segment-scoped budgets (machinery exists; seed is run-only today).
- Optional fail-closed integrity: refuse on missing registration or exceeded budget.
- Remote observe / decide (fatter plane) for multi-host stacks.
- Documentation site.

Status of each control-plane job: [`docs/control-plane-status.md`](docs/control-plane-status.md).

## Documentation

- [Onboarding](docs/guides/onboarding.md): prereqs, bare-min integrate, FAQ, current limits
- [Field guide](docs/guides/field-guide-add-tokenops.md): triad deep dive + screenshots
- [Control plane status](docs/control-plane-status.md)
- [Architecture](docs/architecture.md)
- [Run attribution](docs/run-attribution.md)
- [Control plane deploy](docs/control-plane-deploy.md)
- [Examples](examples/README.md)
- [Product: comparison](docs/product/comparison.md) · [shared ledger](docs/product/shared-ledger.md)

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

## Contributing

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
