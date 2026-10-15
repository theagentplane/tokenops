# Testing TokenOps

How to run the tests, what each suite proves, and how to add a test when you add a policy.
Default CI needs no API key and no vendored framework: the model is scripted, and the control
plane (when a test needs one) is the released `agentplane-control-plane` running in process.

## Run everything

```bash
pip install -e ".[contract]" --group dev
python -m pytest -q
```

Pytest config is in `pyproject.toml` (`testpaths=["tests"]`, `pythonpath=["src", "."]`,
`addopts = "-m 'not live'"`). Use `python -m pytest` on Windows.

```bash
python -m pytest -q tests/test_cost_budget.py      # one policy
python -m pytest -q -k "halt or budget"            # by keyword
python -m pytest -q tests/e2e                      # end to end, real control plane
python -m pytest -q tests/contract                 # contract tests only
```

`tests/contract` and `tests/e2e` are skipped unless `agentplane-control-plane>=1.0` is installed
(the `contract` extra installs it).

## What the suites cover

| Where | Proves |
|---|---|
| `test_ledger.py` | pricing, single-source `cum_spent`, velocity and recent, `budget_left`, in-flight, sticky halt |
| `test_cost_budget.py` ... `test_tool_fix.py` | one per policy: detector plus action (`FakeView`) |
| `test_policies_wrap_integration.py` | all policies through the Governor and `wrap_complete` |
| `test_config.py`, `test_policy_names.py` | `build_governor` from a dict; canonical names across code, YAML and docs |
| `test_tokenops_run.py`, `test_attribution.py` | joining the trace, attribution, fail-closed behaviour when the plane is down |
| `test_crossing_hook.py`, `test_chronicle_boundary.py`, `test_boundary.py` | the Chronicle hook and `@boundary` |
| `test_cross_process_budget_gating.py`, `test_thread_safety.py` | shared spend and halt across Governors on one plane (fake) |
| `test_repositories_*`, `test_async_ledger.py` | the control-plane client and the background writer |
| `tests/contract` | the client and the in-memory fake against a real plane 1.x (the fake is verified) |
| `tests/e2e` | a governed agent trips its budget, two agents share one ledger, a halted trace is replayed with the fix |

## How the tests stay isolated

Helpers in `tests/conftest.py` and `tests/`:

- **`FakeView`**: a `LedgerView` whose reads are fixed by constructor kwargs.
- **`CollectingControls`**: a controls object that records actions (and raises on HALT).
- **`toy_price`**: a deterministic price book.
- **`fake_plane`** (`tests/fake_plane.py`): an in-memory control plane 1.0 behind
  `httpx.MockTransport`, with an `.down` switch for outages.
- **`chronicle_envelopes`**: the envelopes Chronicle recorded, read through a `record` hook.
- **`LocalPlane`** (`tests/local_plane.py`): the real plane, in process on SQLite.

## Adding a policy

1. Add the module under `src/tokenops/control/policies/` and register it in
   `control/config.py` (`POLICY_TEMPLATES`).
2. Add the docs page `docs/policies/<id>.md` and a row to `docs/product/policies-index.md`.
3. Add `tests/test_<id>.py` against `FakeView`, and a case in
   `test_policies_wrap_integration.py`.
4. The control plane must know the template: add it to its allow-list
   (`tests/contract` flags a template the plane does not know).
