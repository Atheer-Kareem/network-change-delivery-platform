# Frozen fleet planning and rollout safety boundary

**Status:** Accepted

**Date:** 2026-08-23

## Context

Increment 5 introduces selector-derived mixed-vendor populations. Approval must
bind the exact devices, interfaces, device-native child plans, no-op members,
and exposure order rather than authorizing a selector whose result may change.
Fleet policy belongs in the Python domain layer and cannot be represented safely
as a shell or CLI loop around single-device deployment.

## Decision

NetBox tag selection is resolved completely and frozen as stable device and
interface identities. One canonical fleet digest transitively binds the typed
selector, exact population, full embedded child `DeploymentPlan` objects,
compliant no-op members, representative canaries, fixed waves, and rollout
policy. Before future execution, the original selector is re-resolved; any
membership or binding drift fails closed. Complete fleet-wide read-only
preflight must succeed before the first device write, and individual
single-device prewrite verification still runs just in time later.

Canaries gate exposure to every later cohort. Increment 5 v1 selects exactly one
deployable member per represented platform using stable inventory identity, then
sorts and partitions remaining deployable members into fixed-size waves. Any
attempted child transaction whose final outcome is not `SUCCEEDED` stops all
later exposure. There are no retries.

Fleet execution will be sequential in Increment 5 v1. Distributed runners,
concurrency groups, overlap locks, and parallel coordination belong to the later
Buildkite hardening increment. Cisco targeted recovery and Junos
commit-confirmed semantics remain the authoritative unchanged device-native
contracts. Prior successful members are not automatically reverted when a later
member fails.

There is no fleet atomicity claim. Partial outcomes must be reported honestly.

## Consequences

Approval remains meaningful across selector drift because it identifies exact
membership and order. Compliant members remain visible without entering write
cohorts. Complete preflight reduces exposure to a partially stale fleet but does
not remove the need for just-in-time device verification or eliminate changes
that occur after the full-fleet check.

Increment 5A implements planning and read-only preflight only. It exposes no
fleet execution method and authorizes no device write.
