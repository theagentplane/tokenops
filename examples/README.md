# TokenOps examples

Runnable A2A test benches and demos (same repo as the TokenOps core library).

| Stack | Agents | Make target |
|-------|--------|-------------|
| Two-agent | Research → Summarize | `make demo` |
| Triad | Planner → Researcher → Writer | `make demo-triad` |
| Brief | Scout → Analyst → Editor (**LangChain** + TokenOps) | `make demo-brief` |
| Bench UI | Chat + Simulator | `make bench-ui` |

## Setup

From the repo root:

```bash
make install   # pip install -e ".[dev,examples]"
cp .env.example .env   # optional API keys
TOKENOPS_CONFIG=examples/config/default.yaml make db-reset
make demo          # plane :7700 + agents + Admin UI
# or
make demo-triad    # plane + planner/researcher/writer + Admin UI
make demo-brief    # plane + scout/analyst/editor (ports 8021–8023)
# smoke brief under run_llm_cap:
#   TOKENOPS_CONFIG=examples/config/brief.yaml TOKENOPS_DB=tokenops-brief.db make db-reset
#   TOKENOPS_DB=tokenops-brief.db make demo-brief   # then in another shell:
#   TOKENOPS_DB=tokenops-brief.db python scripts/smoke_brief.py
make bench-ui      # Chat + Simulator only
```

Docker (two-agent):

```bash
docker compose -f docker-compose.examples.yml up --build
```

Triad overlay:

```bash
docker compose -f docker-compose.examples.yml -f docker-compose.triad.yml up --build \
  tokenops planner researcher writer
```

## Layout

```
examples/
  run.py / run_triad.py / run_brief.py  # demo orchestrators (make demo*)
  a2a/          # shared HTTP helpers
  agents/       # research + summarize
  triad/        # planner + researcher + writer
  brief/        # scout + analyst + editor (LangChain + TokenOps)
  servers/      # python -m entrypoints
  ui/           # Chat + Simulator
  config/       # demo governance YAML seeds
benchmarking/   # MetaGPT / browseruse / trials harness
```

Field guide: [`docs/guides/field-guide-add-tokenops.md`](../docs/guides/field-guide-add-tokenops.md).
Demo screenshots: [`docs/product/demo-bench.md`](../docs/product/demo-bench.md).
