# Examples

Agent stacks that show TokenOps in a multi-agent run: the research to summarize pair under
`agents/`, the planner, researcher and writer triad under `triad/`, and a LangChain stack under
`brief/`, all speaking A2A (`a2a/`).

> **Status.** Each server calls `examples.a2a.tracing.configure_tracing`, which allow-lists its
> peers for `traceparent` injection and turns on `chronicle.instrument_httpx()`, so a hop joins
> the caller's trace. Verified end to end against a real control plane 1.x in `tests/e2e`
> (scripted model, offline search corpus, real servers over HTTP):
>
> | Stack | Test |
> |---|---|
> | `triad/` planner, researcher, writer | `tests/e2e/test_triad_example.py` |
> | `agents/` research to summarize (native) | `tests/e2e/test_research_summarize_example.py` |
> | `brief/` scout, analyst, editor (LangChain) | `tests/e2e/test_brief_example.py` |
>
> Not verified: the LangChain variants under `agents/` (`research` and `summarize`), and any
> run against a live provider. The launcher scripts and `make` targets from 0.4 were removed.
> For an in-process reference use `python -m tokenops.demo`.

## Layout

```
examples/
├── a2a/        # A2A server and client helpers
├── agents/     # research -> summarize (native)
├── triad/      # planner -> researcher -> writer
├── brief/      # scout -> analyst -> editor (LangChain)
├── config/     # example governance YAML (dimension: trace)
└── servers/    # `python -m examples.servers.<name>` entry points
```

## Running one agent server by hand

Start a control plane 1.x, point the agent at it, then start the server:

```bash
export CONTROL_PLANE_URL=http://localhost:8000
export CONTROL_PLANE_API_KEY=...
pip install -e ".[examples]" --group dev
python -m examples.servers.research
```

Hops share a budget through Chronicle's `traceparent` header: configure
`chronicle.configure(inject_hosts=[...])` and `chronicle.instrument_httpx()`.

Reference for the integration itself:
[`.claude/skills/integrate-tokenops/SKILL.md`](../.claude/skills/integrate-tokenops/SKILL.md).
