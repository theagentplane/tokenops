# Testing the TokenOps control plane

How to run the tests yourself, what each suite proves, and how to add a test when you add a
policy. No API keys required — every test runs offline.

---

## Run everything

From `tokenops-dev/`:

```bash
python -m pytest -q
```

You should see **89 passed**. Pytest config lives in `pyproject.toml`
(`[tool.pytest.ini_options]`: `testpaths=["tests"]`, `pythonpath=["src"]`), so no manual
`PYTHONPATH` is needed.

Useful variants:

```bash
python -m pytest -q tests/test_cost_budget.py      # one policy
python -m pytest -q -k "halt or budget"            # by keyword
python -m pytest -v                                # show every test name
python -m pytest -x                                # stop at first failure
```

## What the suites cover

| File | Proves |
|------|--------|
| `test_ledger.py` | pricing, single-source `cum_spent`, velocity/recent, `budget_left` (real + unlimited), inflight, sticky halt, fail-closed |
| `test_cost_budget.py` … `test_output_runaway.py` | one per policy — detector trips on the right input, policy emits the right Action |
| `test_config.py` | `build_governor` wires all 10 policies from a dict; fails closed on unknown policy / missing budget |
| `test_integration.py` | a **real** `NativeResearchAgent` run halts on a budget (model call faked, everything else real) |
| `test_apply.py` | corrective controls through `wrap_complete` (output cap, injected message, blocked dispatch) |
| `test_store.py` | SQLite CRUD, `governance_config_for`, auto-seed, clear/reseed helpers |
| `test_attribution.py` | registration, headers, `build_attribution`, fail-closed resolve |
| `test_boundary.py` | `@boundary` → `Observation` with span + boundary_tags |
| `test_chronicle_boundary.py` | Chronicle envelopes + govern ingest |
| `test_attribution_ledger_policies_e2e.py` | register → ledger → `step_cap` HALT (in-process + HTTP) |
| `test_server_enforcement.py` | Admin store config → live server → HALT → RunRecord |

## How the tests stay isolated

Two helpers in `tests/conftest.py`:

* **`FakeView`** — a `LedgerView` whose reads are fixed by constructor kwargs
  (`FakeView(_budget_left=0)`). A detector is tested with **zero** real ledger and **zero**
  other policies, so one failure points at exactly one unit.
* **`CollectingControls`** — an OUT connector that records Actions (and raises on HALT), so a
  corrective policy's MUTATE/INJECT can be asserted through the real Governor before a
  provider wrap exists.
* **`toy_price`** — a deterministic price book (10 micros/input token, 30/output), fail-closed
  on unknown models.

* **`TOKENOPS_SKIP_GOVERNANCE_SEED=1`** — set in `tests/conftest.py` so test fixtures get an
  empty governance store unless they seed explicitly.

## DB scripts (governance reset)

```bash
make db-clear      # delete all rows (runs + governance)
make db-reseed     # replace governance from default.yaml
make db-reset      # clear + reseed
```

## Try the live halt yourself (offline)

`test_integration.py` is the end-to-end demo. To watch it, run it verbosely:

```bash
python -m pytest -v tests/test_integration.py
```

It builds a Governor from a config dict with a 20,000-micro run budget, swaps the agent's
model call for a fake that always "searches" (so no API key, no network), and runs the real
`NativeResearchAgent`. Each fake model call costs 9,550 micros, so the run halts on the 3rd
call — the test asserts `Halt` propagated and `cost_micros == 9550*3`.

To adapt it into a script, copy the body and print `gov.ledger.cost_micros(run_id)` after
each step.

## Running against a real model (optional)

The bench can call real providers if you set keys (`OPENAI_API_KEY` / `ANTHROPIC_API_KEY` in
`.env` — see `.env.example`). Provider import is lazy, so you only need the SDK for the
provider you use. The control-plane tests never call a real model; only the agent servers do.

## Adding a test when you add a policy

Each policy follows the same shape (`tokenops-lld/policies/<name>.md` documents the contract):

1. **Unit** — instantiate `build(...)`, feed one input via `FakeView`, assert the `Signal`
   severity and the `Action.kind`. Cover: the trip case, the allow case, and any
   escalation (WARN→TRIP after K).
2. **e2e (optional)** — register on a real `Governor`; use `CollectingControls` for
   corrective actions or `RaiseControls` for HALT; drive `observe`/`pre_call` and assert.

Name the file `tests/test_<policy>.py`; pytest discovers it automatically.

## Quick reference — the control-plane public API

```python
from tokenops.control import (
    build_governor,          # config dict -> wired Governor (+ .ledger)
    Governor, Ledger, Budget,
    RaiseControls,           # OUT: HALT only (brownfield)
    ApplyControls, Throttled,# OUT: applies MUTATE/INJECT/REJECT (greenfield wrap)
    make_on_step,            # IN: adapt an agent StepEvent -> Observation
    wrap_complete,           # provider wrap: runs pre_call + applies mutations
    Observation, Halt,
)
```
