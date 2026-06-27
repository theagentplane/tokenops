# Instrumentation + attribution contract (data plane ↔ control plane)

Who does what: the **agent (data plane)** emits telemetry; the **control plane** ingests it.
This is the exact interface between the two, so the finalized A2A research agent and the
control plane can be built in parallel and snap together.

**Run registration and trace dims:** see `docs/run-attribution.md` (authoritative for
`run_id`, `intent`, `user_dims`, span graph, and `boundary_tags`).

Code: `control/integration.py` (`make_on_step`, `wrap_complete`), `control/attribution.py`,
`control/context.py`, `control/core.py` (`Observation`, `Attribution`).

---

## The two seams (all the agent must touch)

| Seam | Direction | Agent provides | Control plane does |
|---|---|---|---|
| `on_step(StepEvent)` | IN | fires a step object after each model / tool / delegate action | `make_on_step` maps it → `Observation` → `governor.observe` (records to ledger, runs observe-policies) |
| `complete_fn(provider, model, messages)` | OUT | calls the injected callable instead of the raw provider | `wrap_complete` runs pre_call policies, applies MUTATE/REJECT, then dispatches |

The agent already has both (`on_step=`, and now a `complete_fn=` param). The server wires
the control-plane versions in. **No other change to agent logic is required.**

## What the IN telemetry must carry (per step)

`make_on_step` builds an `Observation` from the step object by `action`. To be complete, the
agent's step (or the server building `Attribution`) must supply:

| node_type | Required from the agent | Currently |
|---|---|---|
| **llm** (`action="model"`) | token `usage` (input/output; ideally cached/reasoning), and **`provider` + `model`** | usage comes from the step; **provider/model are filled by the adapter** today (`make_on_step(provider=, model=)`) — fine while single-model, revisit if the agent switches models mid-run |
| **tool** (`action="search"/…`) | tool `name` + `args` (→ `signature`), and the result (→ `result_hash`) | adapter derives `signature`/`result_hash` from `query`/`detail`; richer tools should pass real args + a result hash for loop detection |
| **delegate** (`action="delegate"`) | target agent + the child run's `rolled_up_cost_micros` | rollup flows back via the A2A `summarize_response.cost_micros` (already wired) |

## Attribution — the source of segments

Every `Observation` carries an `Attribution`. **Segments are derived from it** — a segment
is just a resolved attribution dimension (`segment_key_for`):

| Dimension | Segment key | Comes from |
|---|---|---|
| run | `run:<run_id>` | generated at the research boundary (uuid) |
| user | `user:<user>` | request payload `user` (today defaults to `"ui"`) |
| agent | `agent:<agent>` | the server (`research` / `summarize`) |
| tenant | `tenant:<tenant>` | **must be supplied** in the request/attribution (today unset) |
| tag | `tag:<key>=<value>` | registration `user_dims` + `intent` |

**To govern or report by tenant / user / a custom tag, the agent path must populate that
dimension.** This is the main instrumentation work on the co-presenter's side: thread
`user`/`tenant`/tags from the request through to `Attribution` so budgets and dashboards can
segment on them. Once present, no control-plane change is needed — `segment_key_for` and the
Admin UI's Segment entity already consume them.

## What we mock today (so both sides progress)

- **Model call**: tests inject a fake `complete_fn` returning a canned `ModelResponse` with
  token counts — no API key, no network (`test_integration.py`, `test_server_enforcement.py`).
- **Step object**: `make_on_step` **duck-types** it (reads `.action`/`.query`/`.tokens`), so
  the control plane never imports the agent package. Any object with those attributes works.

When the finalized agent emits richer attribution (tenant/user/tags), point its `on_step`
at `make_on_step` and set those fields on the server's `Attribution` — done.

## Actuator status (what lands where)

| Control | Status |
|---|---|
| HALT | ✅ raises through `on_step`; boundary returns structured 200 partial |
| MUTATE (model swap / output cap) | ✅ applied in `wrap_complete` (cap reaches the provider via `max_output_tokens`) |
| INJECT (next-call message) | ✅ via `controls.carry`, prepended on the next dispatch |
| REJECT / QUEUE | ✅ `Throttled` → 429 + Retry-After at the boundary |
| MUTATE (programmatic prompt compaction) | ✅ `Action.compact` → `wrap_complete` rewrites outgoing messages (dedup, pin system) |
| INJECT (replace a tool *result*) | ✅ `Action.replace_tool_result` → agent `take_tool_result()` substitutes the result (research-native; `tool_output_cap`) |
| RETRY | ✅ bounded loop in `wrap_complete` — re-issue with tighter cap + raised penalties |
| CANCEL | ✅ built + tested via `wrap_stream` + `providers.stream_chat` (mid-stream teardown); not in the default live path until the server streams |

All seven actuators are implemented and tested. The only live-path gap is CANCEL: the native
agent runs non-streaming, so CANCEL fires only when the server uses `wrap_stream`. Parity
items remaining: `tool_fix` deep tool-result swap, and deep hooks for the summarize/LangChain
variants.
