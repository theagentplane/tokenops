# Code Navigation

How to find your way around the test bench codebase.

## Entry points

| Command | Start reading at |
|---------|------------------|
| `make research-server` | `src/tokenops/servers/research.py` → `agents/research/{native,langchain}/server.py` |
| `make summarize-server` | `src/tokenops/servers/summarize.py` → `agents/summarize/{native,langchain}/server.py` |
| `make ui` | `src/tokenops/ui/app.py` |

## Trace a run (file path)

```text
ui/app.py
  → a2a/client.py submit_task()
    → a2a/server.py POST /v1/tasks
      → research/*/server.py handler
        → agents/factory.py (at server startup)
        → research/*/agent.py run()
          → research/prompts.py
          → providers/factory.py
          → research/*/tools.py → research/tools/core.py → corpus/
        → a2a/client.py delegate_summarize()
          → summarize/*/server.py handler
            → summarize/*/agent.py run()
              → summarize/prompts.py
              → providers/factory.py
      → TaskResponse back to UI
```

## Layer cake (onboarding read order)

1. `agents/types.py`, `agents/protocols.py`
2. `config/schema.py`, `config/loader.py`
3. `providers/`, `agents/research/tools/`
4. `agents/*/agent.py`, `*/prompts.py`
5. `a2a/messages.py`, `a2a/server.py`, `a2a/client.py`
6. `agents/*/server.py`, `servers/`
7. `ui/app.py`

## Framework fork

Only `agents/factory.py` and `{native,langchain}/` folders differ by framework. Prompts, tool core, providers, and A2A layer are shared.

## Quick lookup

| Change… | Open… |
|---------|--------|
| UI | `ui/app.py` |
| Config / presets | `config/schema.py`, `config/presets/` |
| A→B delegation | `a2a/client.py`, `research/*/server.py` |
| A2A payloads | `a2a/messages.py` |
| Search / corpus | `agents/research/tools/core.py` |
| Model APIs | `providers/` |
