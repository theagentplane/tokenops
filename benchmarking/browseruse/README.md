# Browser-use live benchmarks

Vanilla **browser-use** vs **TokenOps-governed** on the same task.

Governance wiring lives under `benchmarking/browseruse/` only.

## Setup

```bash
bash benchmarking/browseruse/setup_live.sh
source benchmarking/browseruse/.venv/bin/activate
```

Set `OPENAI_API_KEY` or `BROWSER_USE_API_KEY` in `.env`.

## Run

```bash
# Demo tasks (recommended starting point)
python benchmarking/browseruse/run_live_benchmark.py --scenario showcase_suite --trials 5 --cooldown-sec 60

# Other suites
python benchmarking/browseruse/run_live_benchmark.py --scenario fair_suite
python benchmarking/browseruse/run_live_benchmark.py --scenario trap_suite
python benchmarking/browseruse/run_live_benchmark.py --scenario cap_suite

# One scenario, JSON output
python benchmarking/browseruse/run_live_benchmark.py --scenario books_verify_trap --trials 1 --json
```

Use `--cooldown-sec 60`–`90` between arms. Default order: vanilla, then TokenOps.

## Config

All live A/B runs use one TokenOps config: **`steering`** (full stack in `configs.py` — `progress_guard`, `cost_guard`, `cost_budget`, tool shaping, etc.).

We do not assign a different config per scenario for demos. Which internal policy fires on a given run varies with agent behavior; that is expected.

INJECT text is appended as the last user turn via `tokenops.control.consume_carry`.

## Suites

| Suite | Scenarios | Notes |
|-------|-----------|-------|
| `fair_suite` | `example_tight_cap`, `books_loop_trap` | Normal tasks — parity check |
| `trap_suite` | `example_verify_trap`, `books_verify_trap` | Prompt forces useless reloads |
| `cap_suite` | `books_pagination_stress`, `books_cost_guard` | Long work, tight cap |
| `showcase_suite` | `books_verify_trap`, `books_pagination_stress` | Best demo candidates |

**Not in standard suites** (dev only): `flight_sfo_india`, `books_tool_fix`, `books_huge_eval`, `example_tool_output_cap`.

### Trap tasks (what “trap” means)

The prompt **tells the agent to waste steps on purpose**:

- `example_verify_trap` — reload example.com nine times before done
- `books_verify_trap` — reload books.toscrape.com ten times before done

Vanilla often obeys and overspends. TokenOps should catch repetition and finish sooner or cheaper — but success is not guaranteed every run.

### Showcase suite

Two **different task shapes**, not two “policy demos”:

1. **`books_verify_trap`** — reload loop under a very tight cap ($0.034)
2. **`books_pagination_stress`** — paginate catalogue page-by-page under cap ($0.10)

Run multiple trials (`--trials 5` or `run_trials_sweep.py`). Pick results where `showcase_pass` is true for slides — do not assume every iteration wins.

## Scoring

Per trial:

| Tag | Meaning |
|-----|---------|
| `ok` | Counted in averages |
| `infra` | Rate limit / empty run — **excluded** from averages |
| `halted` | TokenOps stopped the run |
| `failed` | Agent did not succeed |

Summary fields:

- **`win_type`** — `fewer_steps` (cheaper + fewer steps), `cheaper_steps` (same steps, less spend), `outcome`, `mixed`, `none`
- **`showcase_pass`** — TokenOps spend < vanilla **and** success-within-budget at least as good
- **`savings_per_1k_runs_usd`** — extrapolated $ saved if this delta held for 1k runs

Example:

```bash
python benchmarking/browseruse/run_live_benchmark.py --scenario showcase_suite --trials 1 --json
```

## What we claim in a demo

Safe: “On this reload-loop task, TokenOps cut spend by X% in N trials, and succeeded within budget Y% of the time.”

Not safe: “This scenario proves `progress_guard` fired” or “TokenOps always wins.”

## Files

| File | Role |
|------|------|
| `scenarios_live.py` | Tasks + suite membership |
| `configs.py` | TokenOps governance config |
| `integration.py` | Patches browser-use Agent / LLM / tools |
| `run_live_benchmark.py` | A/B runner + JSON output |
