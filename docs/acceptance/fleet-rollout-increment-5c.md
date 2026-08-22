# Increment 5C fleet rollout acceptance

## Status

Live acceptance is pending exact-plan review and separate explicit fleet-digest
approval. Increment 5 is not complete.

## Scope

Increment 5C completes process-local stable-device overlap admission and will
exercise the reviewed sequential fleet state machine against a synthetic
personal CML fleet containing at least three deployable devices across Cisco IOS
XE and Junos, including a real persisted wave.

Process-local admission reserves every frozen `inventory_object_id`, including
compliant members, atomically before complete preflight. It is not cross-process
or distributed coordination. No filesystem lock is used or claimed.

## Required acceptance flow

1. Inspect CML capacity and bootstrap any third synthetic device outside NCDP.
2. Discover safe unused physical interfaces read-only.
3. Establish exact synthetic NetBox tags, identities, and narrow OpenBao access.
4. Generate one immutable fleet plan through `fleet-plan`.
5. Independently verify its canonical SHA-256 digest.
6. Run complete read-only fleet preflight.
7. Stop for explicit approval of that exact digest.
8. Only a later separately authorized action may run `fleet-deploy` once.

No live fleet deployment or selected-interface write has occurred at this stage.
