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
python benchmarking/run_all.py --trials 3 --limit-usd 1.00 --max-steps 25
```

Single arm:

```bash
python benchmarking/browseruse/run_live_benchmark.py --mode-only ungoverned
python benchmarking/browseruse/run_live_benchmark.py --mode-only tokenops --limit-usd 1.00
```
