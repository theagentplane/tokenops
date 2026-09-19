# Testing the TokenOps control plane

How to run the tests yourself, what each suite proves, and how to add a test when you add a
policy. Default CI runs **everything that needs no real API key or vendored framework** —
including the example-bench end-to-end tests (real servers, real Governor, real policy
HALT/MUTATE decisions; only the model call and search tool are faked, so no network or key
is needed). Only `live` (genuinely needs an API key / vendored framework) is excluded.

---

## Run everything (default CI)

From the repo root:

```bash
python -m pytest -q
```

Pytest config lives in `pyproject.toml` (`testpaths=["tests"]`, `pythonpath=["src", "."]`,
`addopts = "-m 'not live'"`). Only the `live` suite is excluded by default; `e2e` is part of
the regular run precisely so a real run+policy regression can't go unnoticed the way #127
did (two example-bench e2e tests silently broke against `main` for a while because they
were excluded from CI at the time).

Useful variants:

```bash
python -m pytest -q tests/test_cost_budget.py      # one policy
python -m pytest -q -k "halt or budget"            # by keyword
python -m pytest -q -m e2e                         # only the example benches
python -m pytest -q -m live                        # needs keys / vendored frameworks
python -m pytest -v                                # show every test name
python -m pytest -x                                # stop at first failure
```

## What the suites cover

| File | Proves |
|------|--------|
| `test_ledger.py` | pricing, single-source `cum_spent`, velocity/recent, `budget_left`, inflight, sticky halt |
| `test_cost_budget.py` … `test_tool_fix.py` (+ `test_trajectory_hint.py`) | one per policy — detector + Action (`FakeView`) |
| `test_policies_wrap_integration.py` | **all** policies through Governor + mocked `wrap_complete` / observe |
| `test_config.py` | `build_governor` wires policies from a dict |
| `test_integration.py` | in-process wrap + fake model halt |
| `test_apply.py` | corrective controls through `wrap_complete` |
| `test_store.py` | SQLite CRUD, auto-seed, clear/reseed |
| `test_attribution.py` | registration, headers, fail-closed resolve |
| `test_boundary.py` / `test_chronicle_boundary.py` | `@boundary` + Chronicle ingest |
| `test_attribution_ledger_policies_e2e.py` | register → ledger → HALT (in-process + HTTP) |
| `test_cross_process_budget_gating.py` | shared SQLite spend/halt across Governors |
| `test_server_enforcement.py` | Admin store → server → HALT → RunRecord |
| `tests/examples/` | real A2A bench / triad servers, real Governor + policy HALT/MUTATE, real multi-agent shared ledger (marker: `e2e`, no key needed, **now in the default run**) |
| `tests/benchmarking/` | harness unit tests; MetaGPT/browser-use need vendor (marker: `live` where applicable) |

## How the tests stay isolated

Two helpers in `tests/conftest.py`:

* **`FakeView`** — a `LedgerView` whose reads are fixed by constructor kwargs
* **`CollectingControls`** — OUT connector that records Actions (and raises on HALT)
* **`toy_price`** — deterministic price book
* **`TOKENOPS_SKIP_GOVERNANCE_SEED=1`** — set in `tests/conftest.py` so fixtures get an empty store unless they seed explicitly

## DB scripts (governance reset)

```bash
make db-clear      # delete all rows (runs + governance)
make db-reseed     # replace governance from default.yaml
make db-reset      # clear + reseed
```

## Example e2e (offline, mocked LLM — part of the default run)

```bash
pip install -e ".[dev,examples]"
python -m pytest -q -m e2e   # just this slice, e.g. while iterating on it
```

## The control plane in tests (no fake)

The control plane is a **separate repo** (`theagentplane/control-plane`) with its own tests and
CI. Tokenops CI does not run the plane's test suite and should not.

There is also **no fake plane**. Every test that touches the ledger runs against the real
`control_plane.app`, in-process over ASGI on a throwaway SQLite file, through the same
`HttpLedgerBackend` production uses. A hand-written stand-in has to be kept in sync with
the thing it copies, and it wasn't: the old in-memory fake kept `step.compaction` while the
plane dropped it, so tests passed for a feature that did not work (control-plane#18). The
real plane costs about a second across the ledger tests.

Fixtures (`tests/conftest.py`):

| Fixture | Use |
|---------|-----|
| `plane_backend` | `HttpLedgerBackend` over a fresh real plane — the default ledger backend for tests |
| `recording_backend` | the same, wrapped in a spy that records every `apply_events` batch. Use it to assert what the SDK **sent**, independent of what the plane stores |
| `plane_app_factory` | the raw app, when you need to build several planes or set `Settings` |
| `live_plane_url` | a plane on a real TCP port, for `ControlPlaneClient.from_env()` |

The plane is a **required** test dependency (`make install` includes it). A missing install
fails the test instead of skipping it, because a skip reads as a pass.

## Wire-schema compatibility (non-blocking)

Two layers guard the SDK-to-plane wire format:

1. **`tests/test_wire_samples.py` (blocking, no plane).** Every field on `LedgerEvent` must
   have a sample in `tests/wire_samples.py` and an *observer*, a function that reads the
   field back through a public plane read path. Add a field to the TypedDict and this
   fails until you enroll it. It is what makes "the SDK sends a new field" automatically
   become "the plane is checked for it".
2. **`tests/compat/` (non-blocking).** Marked `compat` and excluded from the default run.
   It sends each sample to a real plane and asserts every field comes back. There is one
   case per field, so a failure names it:

   ```
   FAILED tests/compat/test_wire_schema_compat.py::test_plane_keeps_field[step.compaction]
   ```

   CI runs it as a separate `schema-compat` job with `continue-on-error`, against both the
   oldest plane the SDK claims to support (`v0.2.2`, per `pyproject.toml`) and `main`. It
   can fail without blocking a merge: a failure means the plane is older than, or has
   diverged from, the SDK, which is worth knowing but is not an SDK bug.

```bash
make test-compat          # against whatever plane is installed
```

A field the plane accepts but exposes through no read path is listed in `UNOBSERVABLE`
with the reason, so the gap is visible rather than silently untested.

### Changing what the SDK sends the plane

1. **Name the plane-side work in the issue.** "Attach X to the ledger event" is half a task.
   The acceptance criteria must say where X is stored and how it is read back, and link a
   `theagentplane/control-plane` issue for it.
2. **Enroll the field** in `tests/wire_samples.py` (the blocking test tells you to).
3. **Assert what the SDK sends** in a unit test with `recording_backend`.
4. **Land the plane change first.** Until it does, the new field's compat case fails. That
   is expected and non-blocking; do not add an `xfail` to the default suite.
5. **Update the wire contract doc** (`docs/api-contract.md`) in the plane repo in the same
   change that adds the field.
