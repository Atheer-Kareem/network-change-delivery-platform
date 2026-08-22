# Frozen fleet planning and rollout safety boundary

**Status:** Accepted

**Date:** 2026-08-22

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

Fleet execution will be sequential in Increment 5 v1. Increment 5B adds the
canary/wave execution state machine and honest partial outcomes. Increment 5C
adds process-local same-target overlap admission and mixed-vendor live CML fleet
acceptance. Distributed or cross-run locks, runner concurrency groups, and
multi-worker coordination belong to the later Buildkite hardening increment.
Local rollout overlap safety is distinct from distributed runner coordination.
Cisco targeted recovery and Junos commit-confirmed semantics remain the
authoritative unchanged device-native contracts. Prior successful members are
not automatically reverted when a later member fails.

There is no fleet atomicity claim. Partial outcomes must be reported honestly.

## Consequences

Approval remains meaningful across selector drift because it identifies exact
membership and order. Compliant members remain visible without entering write
cohorts. Complete preflight reduces exposure to a partially stale fleet but does
not remove the need for just-in-time device verification or eliminate changes
that occur after the full-fleet check.

Increment 5A implements planning and read-only preflight. Increment 5B adds one
Python-owned sequential execution state machine for an already-approved exact
fleet plan. The fleet digest authorizes its fully embedded child plans; each
child is passed to the unchanged `deploy_plan` boundary with its own exact digest.

Execution requires complete fleet preflight before the first child attempt, then
uses the persisted canary tuple and persisted waves without recomputation. Only a
child `SUCCEEDED` outcome permits further exposure. `RECOVERED`, ambiguity,
staleness, validation failure, and every other outcome stop immediately. Earlier
successes are not reverted, retried, or relabeled, and the fleet record reports
`STOPPED` or `PARTIAL` honestly.

After every deployable child succeeds, one fresh complete read-only validation
checks the desired description on every frozen member. Its failure produces
`FINAL_VALIDATION_FAILED` without rewriting successful child history or issuing
another write. Increment 5B supplies code and offline evidence only; live
mixed-vendor acceptance and process-local overlap admission remain Increment 5C.
