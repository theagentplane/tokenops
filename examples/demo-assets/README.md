# Demo assets — native test agent

Demo is **Research → Summarize** in `src/tokenops/`. UI + Dashboard + Run simulator.

## Start here

**[DEMO_RUNBOOK.md](./DEMO_RUNBOOK.md)** — setup, deck order, clicks, screenshots.

## Architecture

| File | Use |
|------|-----|
| `architecture/test-agent-integration.svg` | Integration points slide |
| `docs/tokenops-architecture.svg` | Control plane overview |
| `architecture/CODE_SCREENSHOTS.md` | Which code lines to screenshot |
| `architecture/agent-pinboard.png` | **Agent hooks pinboard (policies/budgets/governor)** |

## KPI tables

| File | Content |
|------|---------|
| `tables/H1_average_spend_reduction.md` | Shared ledger before/after spend |
| `tables/H2_success_within_budget.md` | Completion under cap |
| `tables/overall_benchmark_table.png` | **Slide-ready KPI table (gold/black PNG)** |
| `tables/archive/browseruse_benchmark_results.md` | Old browser-use bench (not used) |

## Quick start

```bash
cp .env.example .env          # SEARCH_BACKEND=corpus included; add OPENAI only for Test Bench
export SEARCH_BACKEND=corpus
python scripts/prep_ledger_comparison.py
make run
```

Open http://localhost:8501 → **Chat** (governance slider + demo chips).

**Verify live scenarios:**
```bash
python scripts/test_demo_scenarios.py
python scripts/capture_demo_media.py --videos-only   # single reel: governance_demo_all_scenarios.webm
```

**Keys:** Chat chips + Test Bench = **`OPENAI_API_KEY` in repo root `.env`**.
