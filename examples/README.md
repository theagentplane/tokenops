# Examples

Agent stacks that show TokenOps in a multi-agent run: the research to summarize pair under
`agents/`, the planner, researcher and writer triad under `triad/`, and a LangChain stack under
`brief/`, all speaking A2A (`a2a/`).

> **Status.** These were written for TokenOps 0.4, which shipped its own plane and UI. They
> import and use the 1.0 API (`tokenops_run`, `wrap_complete`, `ControlPlaneClient`), but they
> have not been re-verified end to end against a control plane 1.x, and the launcher scripts and
> `make` targets were removed. They are being rewritten; see
> [#162](https://github.com/theagentplane/tokenops/issues/162). For a runnable, tested reference
> use `python -m tokenops.demo` (in process) and `tests/e2e` (a real control plane).

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
