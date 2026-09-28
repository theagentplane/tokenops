# Reviewer traps: issues #114 and #67

This change fixes two enforcement-adjacent gaps. Review and merge it before
starting work that depends on its assumptions.

## #114: governance configuration is part of enforcement

The HTTP SDK used to fetch governance configuration on every run start. A
background refresh must never replace the last known-good configuration with a
failed response, and a hard-expired configuration must not start a run with an
unknown policy set. Follow-up work on plane-unavailable behavior (#129), a
Governor container (#56), policy data scope (#118), or pricing distributed in
governance config (#128) should build on this cache contract rather than add a
second HTTP cache.

## #67: unsupported actions must be observable

`RaiseControls` can only halt a brownfield agent. Its deliberate conversion of a
corrective action to HALT is now a governance event with the policy identity.
Follow-up work on policy audit snapshots (#58), non-bypassable enforcement
(#109), streaming cancellation (#110), or a dashboard should consume this event
rather than infer an escalation from a free-text exception.

## Scope boundary

This does not change the policy decision order, make HTTP ledger events buffered,
or implement multimodal streaming. Those changes need their own compatibility and
failure-mode review.
