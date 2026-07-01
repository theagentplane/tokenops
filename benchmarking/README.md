# TokenOps live benchmarks

Compare **vanilla browser-use** vs **TokenOps-governed** on real tasks.

## Setup

```bash
bash benchmarking/browseruse/setup_live.sh
source benchmarking/browseruse/.venv/bin/activate
```

Set `OPENAI_API_KEY` or `BROWSER_USE_API_KEY` in `.env`.

## Run

```bash
# Policy-focused suite (example.com tight cap + books loop trap)
python benchmarking/run_all.py --scenario policy_suite

# Stress suite (loop traps under tight caps — vanilla overspend vs TokenOps governance)
python benchmarking/run_all.py --scenario stress_suite

# Single scenario
python benchmarking/browseruse/run_live_benchmark.py --scenario books_verify_trap
python benchmarking/browseruse/run_live_benchmark.py --scenario books_loop_trap --mode-only tokenops
```

Scenarios:
- `example_tight_cap` ($0.30 / 12 steps), `books_loop_trap` ($0.50 / 20 steps) — policy suite
- `books_verify_trap` ($0.034 / 20 steps) — reload loop bait; vanilla often overspends on mandatory re-checks while TokenOps `progress_guard` INJECT + `cost_budget` cap spend
- `example_verify_trap` ($0.018 / 15 steps) — nine reload cycles on example.com

Default suite runs vanilla first, 90s cooldown, then TokenOps per scenario.
