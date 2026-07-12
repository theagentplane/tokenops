# Demo runbook — native test agent

**Agent:** Research → Summarize (A2A), `src/tokenops/`  
**UI:** Streamlit at http://localhost:8501  
**No browser-use. No benchmarking/ folder.**

---

## Deck story (20 min)

| # | Slide | Live / asset |
|---|-------|----------------|
| 1 | Problem — multi-agent runs overspend when each agent has its own budget view | `docs/tokenops-architecture.svg` |
| 2 | Architecture — two agents, one control plane, shared ledger | `demo-assets/architecture/test-agent-integration.svg` |
| 3 | Integration — `@boundary` + `wrap_complete` (code screenshots) | See CODE_SCREENSHOTS.md |
| 4 | Instrumentation — Preview mode, leak corpus, control plane trace | Run simulator (live) |
| 5 | Enforcement — shared ledger halts before overspend | Run simulator (live) |
| 6 | Dashboard — run history, cost, halt reason | Dashboard (live) |
| 7 | KPI — spend and completion under cap | `tables/H1_*` and `H2_*` |
| 8 | Optional — full pipeline | Test Bench (live, needs API keys) |

---

## Setup (once)

```bash
cd /Users/susheemkoul/Desktop/tokenops
make install

# Demo env (no API keys needed for Run simulator):
cp .env.example .env
# Edit .env only if you want Test Bench live LLM — add OPENAI_API_KEY (see below)

export SEARCH_BACKEND=corpus   # or set in .env

python scripts/prep_ledger_comparison.py
make run
# → http://localhost:8501
```

### API keys — OpenAI only, one place

There is **no separate key in `benchmarking/`**. Browser-use, MetaGPT, agent servers, and Test Bench all call `load_env()` and read the **same** root `.env`:

```text
tokenops/.env   →   OPENAI_API_KEY=sk-...
```

| Demo part | Keys required? |
|-----------|----------------|
| **Run simulator** (Preview, search loop trap, shared ledger) | **No** — keep **Demo mode ON** |
| **Dashboard / Policy admin** | **No** |
| **Test Bench** + live agents (`make run`) | **Yes** — real `OPENAI_API_KEY` in `.env` |

Both agents use OpenAI (`gpt-4o-mini`) in `src/tokenops/config/default.yaml`. If you already ran live benchmarks on this machine, paste **that same key** into `.env` — it is not checked into git.

**Verify (does not print the key):**

```bash
python3 -c "
from dotenv import dotenv_values
k = dotenv_values('.env').get('OPENAI_API_KEY','')
ok = k.startswith('sk-') and k not in ('sk-...', 'sk-your-openai-key-here') and len(k) > 20
print('OPENAI_API_KEY', 'OK' if ok else 'PLACEHOLDER — paste your key in .env')
"
```

---

## Demo scenarios (pick one in Run simulator)

### Scenario A — `shared_ledger_cap` (hero: multi-agent budget)

**What it proves:** Research + Summarize share one ledger; summarize blocked before overspend.

| Setting | Value |
|---------|--------|
| Demo scenario | **Shared ledger cap** |
| Preview | OFF |
| Corpus | healthy |
| Prep | `python scripts/prep_ledger_comparison.py` |

**Expect:** `halted`, `pre_call_worst_case`, total run $ ≤ $0.001.

---

### Scenario B — `search_loop_trap` (hero: progress_guard)

**What it proves:** Same search query + same tool result repeated → `progress_guard` INJECT (then HALT after max corrections).

| Setting | Value |
|---------|--------|
| Demo scenario | **Search loop trap** |
| Preview | OFF (enforce) or ON (see signal without INJECT) |
| Corpus | leak (auto) |
| Max steps | 12 |
| Env | `export SEARCH_BACKEND=corpus` |

**Why corpus:** offline search returns deterministic snippets per query; `leak` keeps completeness low so the agent does not early-exit.

**Expect in Control plane:** `progress_guard` signals, `INJECT` carry messages, possibly `HALT` after 3+ identical `(signature, result_hash)` pairs (default `repeats: 3`).

---

### Scenario C — `default` (quick sanity)

Two different searches then finish. Does **not** trip `progress_guard`.

---

## Act 1 — Instrumentation (Preview)

**Page:** Run simulator

| Step | Action |
|------|--------|
| 1 | Demo mode **ON** |
| 2 | Preview mode **ON** |
| 3 | Corpus profile **leak** |
| 4 | **Start run** |
| 5 | Tab **Control plane** — policy signals, no halt |
| 6 | Tab **Timeline** — full event log |

**Say:** policies detect and decide; actuators muted in preview.

**Screenshots:** `07_simulator_preview.png`, `08_control_plane_preview.png`

---

## Act 2 — Enforcement (shared ledger)

**Page:** Run simulator (same page)

| Step | Action |
|------|--------|
| 1 | Preview mode **OFF** |
| 2 | Corpus profile **healthy** |
| 3 | **Start run** |
| 4 | Summary bar — **Total run $** vs **Run budget cap** ($0.001) |
| 5 | Status **halted**, halt reason `pre_call_worst_case` |

**Say:** research spends; summarize sees remaining budget; worst-case blocks the call.

**Screenshots:** `09_simulator_halted.png`, `10_control_plane_halt.png`

Reference assets (if pre-captured): `docs/assets/shared-ledger-comparison/`

---

## Act 3 — Dashboard

**Page:** Dashboard

| Step | Action |
|------|--------|
| 1 | Show runs from Acts 1–2 |
| 2 | Expand **Active governance** — 10 policies |
| 3 | Toggle **Problematic only** |
| 4 | **Failure detail** — halt_reason + detector |

**Screenshots:** `11_dashboard_runs.png`, `12_dashboard_governance.png`

---

## Act 4 — Full pipeline (optional)

**Page:** Test Bench

| Step | Action |
|------|--------|
| 1 | Confirm Research + Summarize **online** |
| 2 | Corpus **healthy** |
| 3 | **Run pipeline** |
| 4 | Summary + step log + token usage |

Requires API keys in `.env`. Skip if offline — simulator is enough.

---

## Code screenshots (integration slide)

| Hook | File | Lines |
|------|------|-------|
| LLM wrap | `src/tokenops/agents/research/native/server.py` | 90–93 |
| Tool boundary | `src/tokenops/agents/research/native/agent.py` | 36–53 |
| Governor setup | `src/tokenops/control/config.py` | 113–147 |
| Shared ledger | `src/tokenops/control/store.py` | ledger tables (mention in talk) |

Full list: `demo-assets/architecture/CODE_SCREENSHOTS.md`

---

## KPI slides

Use `demo-assets/tables/overall_benchmark_table.png` for the KPI slide (gold/black theme).

Source markdown: `tables/H1_*.md` and `tables/H2_*.md`. Re-generate PNG:

```bash
python scripts/generate_benchmark_table_png.py
```

Browser-use benchmark tables are archived in `tables/archive/` (not part of this demo).

---

## Reset between takes

```bash
make db-reset
python scripts/prep_ledger_comparison.py
```
