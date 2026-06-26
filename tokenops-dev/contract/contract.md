# TokenOps Control Plane

TokenOps watches what your AI agents spend and stops a run when it goes wrong. Your agents do not change.

Three modules in a line, with two connectors at the edges. Each step has one input, one output, and one handoff to the next step. That is the whole system.

## Contents

1. [Scope](#scope)
2. [Overview](#overview)
3. [Shapes](#shapes)
4. [Lifecycle](#lifecycle)
5. [Module 1: Instrument](#module-1-instrument)
6. [Module 2: Attribute](#module-2-attribute)
7. [Module 3: Enforce](#module-3-enforce)
8. [Connectors](#connectors)
9. [Execution model](#execution-model)
10. [Hard cases](#hard-cases)
11. [Plugging into an agent](#plugging-into-an-agent)
12. [Extending](#extending)

## Scope

TokenOps governs an **agent workflow**: one run that may involve a single agent or several agents handing off to each other. A single agent is just the simple case, a workflow with no hand-offs.

- **One run, one `run_id`.** Every model call, tool call, and delegation in the run carries it.
- **Multi-agent is first class.** When one agent delegates to another, the child runs under the same run, linked by `parent_run`, and its cost rolls up to the parent through `Delegation.rolled_up_cost_micros`. A budget covers the whole workflow, not one agent.
- **In or across processes.** The same contract holds whether the agents share one process or run as separate services. See Execution model.

What it does **not** do: it does not orchestrate the workflow. It never decides which agent or tool runs next; the agent framework does that. TokenOps only measures, attributes, and enforces spend.

## Overview

```
            IN                                                    OUT
 your agent ───▶ Instrument ───▶ Attribute ───▶ Enforce ───▶ your agent
 (telemetry)      measure         tag &           watch &      (controls)
                  & price         remember        act
```

The handoff chain, showing the shape passed at each arrow:

```
agent
  │  raw Event
  ▼
IN.emit ──▶ Instrument ──▶ Attribute ──▶ Enforce ──▶ OUT.apply ──▶ agent
            priced Event   Event +        Action       stop or
                           LedgerView                  steer
```

| Step | In | Out | Hands off to |
|------|----|----|--------------|
| IN connector | a raw call from the agent | a raw `Event` | Instrument |
| Instrument | a raw `Event` | a priced `Event` | Attribute |
| Attribute | a priced `Event` | `Event` (tagged) + `LedgerView` | Enforce |
| Enforce | `Event` + `LedgerView` | an `Action` | OUT connector |
| OUT connector | an `Action` | stop or steer the run | the agent |

The only things that cross a module boundary are `Event`, `LedgerView`, and `Action`. Build any module against those three shapes and you never need another module's code.

## Shapes

The types that pass between modules. Keep them small and frozen.

```
Usage(input, output, cached, reasoning)              # token counts for one call
Attribution(user, agent, run_id, parent_run=None)    # whose spend it is

Event(attr, step, ts, cost_micros)                   # one thing that happened, priced
  ModelCall(+ provider, model, usage)
  ToolCall(+ name, args, signature)                  # signature = hash(name, args)
  Delegation(+ target_agent, child_run, rolled_up_cost_micros)

CallRequest(attr, provider, model,                   # a call about to happen
            estimated_input_tokens=0, max_output_tokens=None)

Signal(detector, severity, run_id, reason)           # severity: OK | WARN | TRIP
Action(kind, run_id, reason)                          # kind: ALLOW | HALT | THROTTLE | DOWNGRADE | PAUSE
Halt(action)                                          # stops the run; extends BaseException (see Connectors)
```

Cost is `cost_micros`, an integer in micro dollars ($1 is 1,000,000). Compare cost, never raw tokens, because tokens are not comparable across providers.

`LedgerView` is the run state Enforce reads. Attribute owns it, so it is defined with Module 2 below.

### Telemetry: OpenTelemetry GenAI

TokenOps keeps the small shapes above in memory, and emits them on the wire as **OpenTelemetry GenAI** spans. That is the same telemetry standard Grafana, Jaeger, Datadog, and the OTel and Microsoft agent stacks already read, so your data is never locked into a custom format. Instrument does the mapping:

| TokenOps | OpenTelemetry GenAI attribute |
|----------|-------------------------------|
| `ModelCall.provider` | `gen_ai.provider.name` |
| `ModelCall.model` | `gen_ai.request.model` |
| `Usage.input` | `gen_ai.usage.input_tokens` |
| `Usage.output` | `gen_ai.usage.output_tokens` |
| `Usage.cached` | `gen_ai.usage.cached_tokens` (provider extension) |
| `Usage.reasoning` | `gen_ai.usage.reasoning_tokens` (provider extension) |
| `ToolCall.name` | `gen_ai.tool.name` |
| `kind` | `gen_ai.operation.name` (chat, execute_tool, invoke_agent) |
| `Attribution.run_id` | `gen_ai.conversation.id` |

Token and model attributes are stable in OTel. `cached` and `reasoning` ride as provider extensions until OTel promotes them. **Cost stays a TokenOps field** (`cost_micros`): OTel carries tokens, not price, so the cost layer is ours.

## Lifecycle

One run, start to stop, showing the call made at each step.

1. **Run starts.** `run_id = Attribute.open_run(user, agent)`
   Every event below carries this `run_id`.

2. **Before a model call.** `signal = Enforce.pre_call(request, view)`
   The guard refuses the call if the budget cannot cover its worst case: current spend, plus the input cost, plus the cost of the model's `max_output_tokens`. If the model set no cap, the guard sets one, so a single response cannot blow the budget before the first chunk arrives.

3. **The call happens.** `event = Instrument.meter("model", provider, model, usage, step, ts)`
   Reads the token totals and fills in `cost_micros`.

4. **Tag and store.** `event = Attribute.record(event, run_id)`
   Stamps who it belongs to and adds its cost to the ledger.

5. **Check it.** `signal = Enforce.observe(event, view)`   where `view = Attribute.view()`
   Looks at the event and the running totals for trouble.

6. **A tool call.** Same path: `meter("tool", ...)`, then `record(...)`, then `observe(...)`.
   Its `signature` lets Enforce spot the same call repeating.

7. **A hand off.** A child agent runs under the same `run_id`, and its cost rolls up through `Delegation.rolled_up_cost_micros`.

8. **A hang.** If a call emits nothing, a timer still checks: `signal = Enforce.tick(now, view)`.

9. **A breaker trips.** `action = Policy.decide(signal, view)` then `Controls.apply(action)`.
   A `HALT` raises `Halt`, which stops the run, carrying the cost so far.

10. **The run ends.** The ledger holds the full cost, split by user, agent, and run.

Steps 2 to 9 repeat for every call until the agent finishes or a breaker stops it.

## Module 1: Instrument

Measure each call and price it.

**Input** &nbsp; a raw `Event` (a model, tool, or delegation occurrence with token usage but no cost yet).
**Output** &nbsp; the same `Event` with `cost_micros` filled in.
**Hands off to** &nbsp; Attribute, which will tag and store it.

**Signatures**
```
price(provider: str, model: str, usage: Usage) -> int          # cost in micro dollars
meter(kind: str, provider: str, model: str, usage: Usage,
      step: int, ts: float, partial: bool = False) -> Event     # the priced Event

# meter(...) returns, for example:
#   ModelCall(attr=…, step=3, ts=…, cost_micros=1500,
#             provider="openai", model="gpt-4o-mini",
#             usage=Usage(input=2000, output=200, cached=1800, reasoning=0))
```

**Rules**
1. Read the usage totals, including `cached` and `reasoning`.
2. Cost is an integer in micro dollars.
3. Unknown price raises. Never return zero.
4. A streaming call may be priced from partial deltas (`partial=True`) so Enforce can trip mid stream. **Partial events carry incremental cost deltas only, never running totals.** The final event carries the reconciling delta so the sum equals the provider's authoritative total. This lets `Attribute.record()` always add and never double count.
5. Emit each `Event` as an OpenTelemetry GenAI span (see Shapes, Telemetry), so the data flows into existing observability tools with no extra work.

**Build alone** &nbsp; Give it a fake `Usage`, check the `cost_micros` on the returned `Event`. Mock the price table. No other module needed.

## Module 2: Attribute

Tag each event with who it belongs to, and remember the run's totals.

**Input** &nbsp; a priced `Event` from Instrument, plus the run identity (`run_id`).
**Output** &nbsp; the `Event` stamped with `Attribution`, stored in the ledger; and a `LedgerView` of the run.
**Hands off to** &nbsp; Enforce, which reads the `Event` and the `LedgerView`.

**Signatures**
```
open_run(user: str, agent: str,
         budget_micros: int | None = None,
         parent_run: str | None = None) -> str        # returns a new run_id
record(event: Event, run_id: str) -> Event            # stamps attribution, updates ledger
view() -> LedgerView                                  # the read only window (see Shapes)
```

**Rules**
1. `run_id` is unique per run. A delegated child carries the parent's `run_id`.
2. A child run's cost rolls up into its parent.
3. Each `record` adds the event's `cost_micros` to the running totals (partials are deltas, so addition never double counts), keeping reads cheap.
4. `record` is safe under concurrency. Parallel calls in one run (for example `asyncio.gather`) assign `step` and update totals atomically, so they do not race. The lock is per `run_id` in one process, and a shared atomic store across many (see Execution model).

**Build alone** &nbsp; Feed it hand made `Event` objects, check the `LedgerView` totals. Needs no meter and no breaker.

### What is a LedgerView

Attribute keeps a **ledger**: the store of every event in a run and its running totals. A **LedgerView** is the read only window onto that ledger. Attribute hands it to Enforce so Enforce can ask about the run but cannot change it. It answers:

```
cost_micros(run_id)            # how much the run has spent so far
step_count(run_id)             # how many events so far
cache_hit_rate(run_id, window) # how well caching is holding up
recent(run_id, n)              # the last n events, for spotting repeats
```

A breaker reads these to decide if a run is going wrong. It never writes.

## Module 3: Enforce

Watch the run and stop or steer it.

**Input** &nbsp; an `Event` and a `LedgerView` from Attribute. Before a call, a `CallRequest`.
**Output** &nbsp; an `Action`. Raises `Halt` to stop the run.
**Hands off to** &nbsp; the OUT connector, which applies the `Action` to the agent.

**Signatures**
```
Detector.pre_call(request: CallRequest, view: LedgerView) -> Signal | None   # before a call
Detector.observe(event: Event,          view: LedgerView) -> Signal | None   # after each event
Detector.tick(now: float,               view: LedgerView) -> Signal | None   # on a timer
Policy.decide(signal: Signal, view: LedgerView) -> Action                    # signal to action
Controls.apply(action: Action) -> None                                       # HALT raises Halt

# decide(...) returns, for example:
#   Action(kind="HALT", run_id="run-001", reason="tool 'search' repeated 3x")
```

A `Detector` is a breaker: it watches and emits a `Signal`. A `Policy` turns a `Signal` into an `Action`. `Controls` carries the `Action` out.

**Rules**
1. A `Detector` reads the ledger, never writes.
2. Prefer `recent(n)` and the cheap totals over scanning all events.
3. An action it cannot perform falls back to `HALT`, never a silent skip.
4. `pre_call` checks the worst case, not just current spend: refuse if `cost so far + cost(estimated_input_tokens) + cost(max_output_tokens)` would pass the budget. If the model set no output cap, the guard sets one.

**Build alone** &nbsp; Feed it fake events and a fake `LedgerView`, check it raises `Halt` when a tool repeats or cost passes the budget.

## Connectors

Your agent only ever touches two functions: `emit` sends a call in, `apply` carries a decision out. Everything between them is the three modules, which the agent never imports.

```
agent ──emit(call)──▶ [ Instrument ▸ Attribute ▸ Enforce ] ──apply(action)──▶ agent
       IN connector            the three modules             OUT connector
```

### IN connector: emit

The single way in. The agent reports a call, and `emit` runs it through the whole pipeline.

**Input** &nbsp; the facts of one call: kind (model or tool), provider, model, token usage. `emit` builds these into a raw `Event`.
**Output** &nbsp; none. `emit` pushes the `Event` through Instrument, then Attribute, then Enforce.
**Signature** &nbsp; `emit(event: Event) -> None`
**Hands off to** &nbsp; Instrument, the first module.

How you wire it:
- **Greenfield** &nbsp; `cp.wrap(model_client)` and `run.record_tool(...)` call `emit` for you.
- **Brownfield** &nbsp; an adapter maps the agent's existing step callback to `emit`. No change to the agent loop.

### OUT connector: apply

The single way out. Enforce calls it whenever a breaker fires, and `apply` carries out the decision.

**Input** &nbsp; an `Action` from Enforce.
**Output** &nbsp; an effect on the run: `ALLOW` proceeds, `THROTTLE` / `DOWNGRADE` / `PAUSE` steer it, `HALT` stops it.
**Signature** &nbsp; `apply(action: Action) -> None`
**Hands off to** &nbsp; the agent.

An action `apply` cannot perform falls back to `HALT`, never a silent skip. Two safeguards make a `HALT` reliable inside heavy frameworks:

1. `Halt` extends `BaseException`, not `Exception`, so a framework's broad `try/except Exception` cannot swallow it.
2. On a `HALT` the run is marked halted (in the ledger, or a shared store across services). The IN connector checks this before the next call and refuses it, so even if the exception is caught and logged, no further spend happens. This is the out of band kill switch.

## Execution model

The contract is the same whether you run in one process or many. Only the **ledger** and the **OUT connector** swap backend.

**Single process (default).**
- The ledger lives in memory.
- Concurrency is handled by a per `run_id` lock.
- A `HALT` raises `Halt`, which unwinds the local loop.

**Distributed (agents across services, or tools behind MCP).**
- The ledger is a pluggable backend. Use a shared atomic store such as Redis, so concurrent nodes increment one counter without racing. Atomicity is the store's job, not a local lock.
- The run's halted flag lives in that shared store. Every IN connector reads it before a call, so a stop decided on one node refuses the next call on every node. This is the cross process kill switch.
- `OUT.apply` performs a network side effect, not only a local raise: it sets the halted flag, and may send a revocation token to the API gateway in front of downstream tools. The local `Halt` is the fast in process path; the shared flag is the cross process path. A microservice that swallows `Halt` still sees the flag on its next call.

In one line: the IN and OUT connectors are a code wrapper in one process, and an API gateway contract across services. The three modules and the shapes do not change.

## Hard cases

The edge cases this contract is built to survive.

- **Streaming calls.** A call that streams for minutes cannot blow the budget unseen. `pre_call` bounds the worst case before it starts, and Instrument prices partial deltas so Enforce can trip mid stream. See Instrument rule 4 and Enforce rule 4.
- **Frameworks that swallow exceptions.** LangChain, CrewAI and others wrap calls in broad `try/except Exception`. `Halt` extends `BaseException` to dodge that, and a halted run flag stops the next call even if the exception is caught. See Connectors, OUT.
- **Parallel tool calls.** Concurrent `record()` does not race: `step` and totals update atomically. See Attribute rule 4.
- **Distributed agents.** When agents span separate services or MCP servers, the ledger moves to a shared atomic store and the halted flag becomes the cross process kill switch, so a stop on one node halts the whole run. See Execution model.

## Plugging into an agent

`cp` is the assembled control plane: the three modules wired behind the two connectors.

```
# greenfield, written with TokenOps from the start
with cp.run(user="alice", agent="research") as run:
    client = cp.wrap(model_client)        # IN connector, automatic
    run.record_tool("search", {"q": q})   # IN connector, for tools

# brownfield, no change to the agent loop
cp.register(SemanticLoop(), BudgetCap(limit_micros=500_000), HaltOnTrip())
agent.run(task, on_step=cp.on_step())     # cp.on_step() is the IN connector
```

A trip raises `Halt` through the OUT connector, which travels up through the agent and stops the run.

## Extending

| To add | Do this |
|--------|---------|
| an event kind | subclass `Event` |
| a breaker | subclass `Detector`, write one hook, register it |
| a response | add an `ActionKind`, handle it in `Controls.apply` |
| a price table | implement `price(...)` |
| a distributed backend | implement the ledger store and the OUT side effect |

None of these touch another module.
