# Migrating from 1.x to 2.0

2.0 removes what 1.1 deprecated. There is no behaviour change: the objects are the same, only
the import paths and a few alias names are gone.

## `tokenops.control` is removed

Import from `tokenops`, or from the layer that owns the module.

| 1.x import | 2.0 import |
|---|---|
| `tokenops.control.{attribution,boundary,config,context,core,engine,ledger,models,pricing,request_context,usage,policy_labels}` | `tokenops.framework.<same name>` |
| `tokenops.control.policies.<policy>` | `tokenops.framework.policies.<policy>` |
| `tokenops.control.{crossing,run,ledger_writers,chronicle_trace_utils}` | `tokenops.capabilities.<same name>` |
| `tokenops.control.integration` (`wrap_complete`, `wrap_stream`, `make_on_step`, `step_to_observation`) | `tokenops.capabilities` (`complete_wrapper`, `stream_wrapper`, `step_observation`) |
| `tokenops.control.{http,instrument}` | `tokenops.interfaces.<same name>` |
| `from tokenops.control import X` | `from tokenops import X` where `tokenops` exports it, else `tokenops.framework`, `tokenops.capabilities`, `tokenops.interfaces` or `tokenops.repositories` |

A mechanical rewrite of `tokenops.control.<module>` to the layer above covers most code; the
1.1 `DeprecationWarning` named the new path for each import.

## Renamed names lose their aliases

| 1.x name | 2.0 name |
|---|---|
| `RunRegistration` | `HopAttribution` |
| `RunNotRegisteredError` | `NoGovernanceScopeError` |
| `bound.registration` | `bound.hop` |
| `current_registration`, `bind_registration` | `current_hop`, `bind_hop` |
| `require_registration`, `merge_registration_dims` | `require_hop`, `merge_hop_dims` |
