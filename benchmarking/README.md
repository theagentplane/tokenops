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

# Single scenario
python benchmarking/browseruse/run_live_benchmark.py --scenario example_tight_cap
python benchmarking/browseruse/run_live_benchmark.py --scenario books_loop_trap --mode-only tokenops
```

Scenarios: `example_tight_cap` ($0.30 / 12 steps), `books_loop_trap` ($0.50 / 20 steps).
Default suite runs vanilla first, 90s cooldown, then TokenOps per scenario.
