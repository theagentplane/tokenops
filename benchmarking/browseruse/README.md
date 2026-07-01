# Browser-use live benchmarks

Live A/B runs compare **vanilla browser-use** vs **TokenOps-governed** runs on the same task. Each arm uses the same LLM and `max_steps`; TokenOps adds soft steering (INJECT), hard budget caps (`cost_budget`), and tool-result shaping.

Governance wiring lives only under `benchmarking/browseruse/` — no changes to `src/tokenops/` or MetaGPT.

## Setup

```bash
bash benchmarking/browseruse/setup_live.sh
source benchmarking/browseruse/.venv/bin/activate
```

Set `OPENAI_API_KEY` or `BROWSER_USE_API_KEY` in `.env` at the repo root.

## Run

```bash
# Four-scenario cost showcase (recommended for demos)
python benchmarking/browseruse/run_live_benchmark.py --scenario cost_showcase_suite --cooldown-sec 60

# Other suites
python benchmarking/browseruse/run_live_benchmark.py --scenario policy_suite
python benchmarking/browseruse/run_live_benchmark.py --scenario stress_suite
python benchmarking/browseruse/run_live_benchmark.py --scenario steer_suite

# Single scenario
python benchmarking/browseruse/run_live_benchmark.py --scenario books_verify_trap
python benchmarking/browseruse/run_live_benchmark.py --scenario example_verify_trap --mode-only tokenops

# Via run_all
python benchmarking/run_all.py --framework browseruse --scenario cost_showcase_suite --cooldown-sec 60
```

Use `--cooldown-sec 60`–`90` between arms when running multiple scenarios back-to-back to avoid OpenAI rate limits. Default order: vanilla first, then TokenOps per scenario.

## Governance presets

Presets live in `configs.py` and map to scenario `governance_preset` fields.

| Preset | Policies emphasized | Behavior |
|--------|---------------------|----------|
| `steering` | Full stack | Default: `progress_guard`, `cost_guard`, `tool_fix`, `tool_output_cap`, `context_compaction`, `output_runaway` |
| `cost_guard` | `cost_guard` at 75% | Budget-pressure INJECT to shorten output; looser `progress_guard` |
| `tool_fix` | `tool_fix` narrow registry | INJECT when agent uses actions outside allow-list (e.g. `click`) |
| `tool_output_cap` | `tool_output_cap` at 3500 tokens | Substitutes oversized tool payloads with offload descriptor |

Shared on all presets: `cost_budget` (hard cap backstop).

INJECT carry is appended as the **last user message** via `tokenops.control.consume_carry` (main agent LLM only in browser-use). Tool policies use `take_tool_result()` after `Tools.act` to substitute `ActionResult` text.

## Cost showcase scenarios (live results)

Four scenarios in `COST_SHOWCASE_SUITE`, each highlighting a different TokenOps cost strategy. Results from live runs (2026-07-01, `gpt-4o-mini`, 1 trial per arm).

```bash
python benchmarking/browseruse/run_live_benchmark.py --scenario cost_showcase_suite --cooldown-sec 60
```

| Scenario | Optimization | Cap | Live win (spend) |
|----------|--------------|-----|------------------|
| `example_verify_trap` | `progress_guard` | $0.018 | −65% |
| `books_verify_trap` | `progress_guard` + `cost_budget` | $0.034 | −73%, success within cap |
| `books_cost_guard` | `cost_guard` minimize | $0.052 | −16% to −49% |
| `books_pagination_stress` | `cost_budget` | $0.10 | −74%, vanilla fails |

Live runs have variance (browser timing, loop compliance). Re-run the suite for fresh numbers before publishing.

---

### 1. `progress_guard` — reload loop on example.com

**Scenario:** `example_verify_trap`  
**Preset:** `steering` · **Cap:** $0.018 · **Max steps:** 15

Task requires nine reload cycles on https://example.com before calling `done`. Vanilla follows the reload bait and overspends; TokenOps detects repeated navigation signatures and injects a steer-to-finish message.

| Arm | Result | Spend | Steps |
|-----|--------|-------|-------|
| Vanilla | ok | $0.072 | 7 |
| TokenOps | ok | $0.025 | 3 |

**Win: −65% spend**, both succeed. TokenOps finishes in fewer steps before loop fully executes.

```bash
python benchmarking/browseruse/run_live_benchmark.py --scenario example_verify_trap --cooldown-sec 60
```

---

### 2. `progress_guard` + `cost_budget` — verify-loop on books.toscrape.com

**Scenario:** `books_verify_trap`  
**Preset:** `steering` · **Cap:** $0.034 · **Max steps:** 20

Find “A Light in the Attic”, then reload the homepage and re-check at least ten times. Vanilla complies with the quality protocol (~$0.09); TokenOps breaks the loop early and stays under cap.

| Arm | Result | Spend | Steps | Within cap |
|-----|--------|-------|-------|------------|
| Vanilla | ok | $0.091 | 9 | no |
| TokenOps | ok | $0.025 | 3 | yes |

**Win: −73% spend**, TokenOps success within cap (+1 vs vanilla).

```bash
python benchmarking/browseruse/run_live_benchmark.py --scenario books_verify_trap --cooldown-sec 60
```

---

### 3. `cost_guard` — minimize steer near budget threshold

**Scenario:** `books_cost_guard`  
**Preset:** `cost_guard` · **Cap:** $0.052 · **Max steps:** 18

Multi-category browse (Travel → Poetry → book above £30). Vanilla often overshoots the cap; `cost_guard` injects a minimize directive around 75% spend so TokenOps trims output before the hard `cost_budget` halt.

| Arm | Result | Spend | Steps |
|-----|--------|-------|-------|
| Vanilla | ok | $0.061–0.098 | 5–9 |
| TokenOps | ok / halted at cap | $0.050–0.051 | 5–7 |

**Win: −16% to −49% spend** depending on trial. Best clean run: vanilla $0.061 → TokenOps $0.051, both succeed. High-variance scenario — prefer median across 2+ trials for demos.

```bash
python benchmarking/browseruse/run_live_benchmark.py --scenario books_cost_guard --cooldown-sec 60
```

---

### 4. `cost_budget` — deep pagination under tight cap

**Scenario:** `books_pagination_stress`  
**Preset:** `steering` · **Cap:** $0.10 · **Max steps:** 22

Find “The Requiem Red” by clicking “next” page-by-page from page 1 (no URL jumps). Vanilla paginates until budget blows out; TokenOps halts near cap, often with task complete.

| Arm | Result | Spend | Within cap |
|-----|--------|-------|------------|
| Vanilla | fail | $0.191 | no |
| TokenOps | ok | $0.050 | yes |

**Win: −74% spend**, vanilla fails while TokenOps succeeds within cap.

```bash
python benchmarking/browseruse/run_live_benchmark.py --scenario books_pagination_stress --cooldown-sec 60
```

---

## Other scenario suites

| Suite | Scenarios | Purpose |
|-------|-----------|---------|
| `policy_suite` | `example_tight_cap`, `books_loop_trap` | Easy tasks — usually no meaningful delta |
| `stress_suite` | `example_verify_trap`, `books_verify_trap`, `books_pagination_stress` | Loop traps and pagination under tight caps |
| `steer_suite` | `books_cost_guard`, `books_tool_fix`, `books_huge_eval` | Per-actuator wiring (`cost_guard`, `tool_fix`, `tool_output_cap`) |

Scenario definitions: `scenarios_live.py`. Governance presets: `configs.py`. Adapter wiring: `integration.py`, `governed_llm.py`, `governed_tools.py`.
