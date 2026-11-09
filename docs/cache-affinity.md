# Cache affinity

A provider's prompt cache lives on the replica that served an earlier call. An agent run whose
calls are spread over replicas loses the cache discount. Cache affinity sends one routing hint
per run so the run's calls reach one replica. It is a transport setting: it never changes
`messages`, `model`, sampling or the output cap, and it works with governance off.

It is **off by default**. Turn it on per wrapper:

```python
governed = wrap_complete(governor, controls, attr, provider="azure", model="gpt-5-mini",
                         dispatch=dispatch, cache_affinity="auto")
```

`cache_affinity` is `None` (off), `"auto"`, or `{"mode": ..., "key": ...}`:

| `mode` | Sends |
|---|---|
| `"off"` | nothing |
| `"auto"` | what the provider table says (below); nothing for a provider not in it |
| `{"body_field": "prompt_cache_key"}` | that field in the request body (`extra_body`) |
| `{"header": "x-session-affinity"}` | that header (`extra_headers`) |

`key` is `"run"` (default: one key per `trace_id`, constant across the run's calls including
`output_runaway` retries, different between runs) or `"fixed:<string>"` for debugging.

## Provider table (`auto`)

Only providers confirmed in their docs or by a probe are listed. Others need an explicit mode.

| Provider | Hint |
|---|---|
| `openai`, `azure` | body field `prompt_cache_key` |

Not covered: Anthropic, Bedrock and Gemini cache explicit prefix markers, not a key; that is a
separate design.

## Fail-soft

If the provider refuses the hint (the error names the field or header), the call is re-sent once
without it and the rest of the run stays unkeyed. An unrelated error, such as a content-filter
400, is raised and does not switch the hint off.

The built-in dispatch (`tokenops.providers.complete`) forwards `extra_body` and `extra_headers`
for `provider="openai"` only. It has no Azure client, so with `provider="azure"` use a custom
`dispatch` that accepts and forwards `**kwargs` (as the benchmark adapter does).

## What is recorded

When affinity is on, each envelope carries `tokenops.cache_affinity` = `sent` or `refused`. When
it is off, nothing is added.

## Benchmarks

The effect is large (about 23% of cost on a 25-task SWE-bench run with `azure/gpt-5-mini`),
larger than most policy effects. A benchmark comparing a TokenOps arm with a vanilla arm must
apply the same hint to **both**, or turn it off in both; otherwise the key's gain is credited to
the policies.
