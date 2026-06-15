# TokenOps Test Bench

A two-agent research pipeline test bench. **Research** (Agent A) runs a search loop, then delegates findings to **Summarize** (Agent B) over A2A-style HTTP. Agents run as separate processes with swappable **native** or **LangChain** implementations.

## Quick start

```bash
make install
cp .env.example .env   # add your API keys

make run               # starts both agents + UI (Ctrl+C stops all)
```

Or run each process separately:

```bash
# Terminal 1
make research-server

# Terminal 2
make summarize-server

# Terminal 3
make ui
```

Open http://localhost:8501. Configure agents in the sidebar, then click **Run pipeline**.

API keys live in a **`.env`** file at the repo root (loaded by both agent servers). Copy `.env.example` to `.env` and set:

- `OPENAI_API_KEY` — if research (or any agent) uses OpenAI
- `ANTHROPIC_API_KEY` — if summarize (or any agent) uses Anthropic

You can still `export` keys in your shell; those override `.env`.

## Search tool

Research uses **DuckDuckGo** by default ([`ddgs`](https://pypi.org/project/ddgs/) package) — free, no API key.

| Corpus profile | Behavior |
|----------------|----------|
| `healthy` | Real web snippets with heuristic completeness score |
| `leak` | Same results, garbled (truncation, masked prices, low completeness) |

## Configuration

Default config: [`src/tokenops/config/default.yaml`](src/tokenops/config/default.yaml)

Presets for all four framework combos: [`src/tokenops/config/presets/`](src/tokenops/config/presets/)

Set a custom config path:

```bash
export TOKENOPS_CONFIG=path/to/config.yaml
make research-server
```

## Architecture

- UI sends task to **research server** only
- Research server completes research, then calls **summarize server** via A2A HTTP
- Summarize returns summary to research; research returns full result to UI

See [`docs/code-navigation.md`](docs/code-navigation.md) for code navigation diagrams.

## Documentation

- [Why Token Governance?](docs/why-token-governance.md)
- [Agent Spec](docs/agent-spec.md)
- [Code Navigation](docs/code-navigation.md)
