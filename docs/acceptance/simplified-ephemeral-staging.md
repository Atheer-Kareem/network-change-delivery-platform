# Simplified ephemeral staging acceptance

## Decision

Starting from merged main `59a403f105ab9ad8fc1ffafb176c6d5a8e7af688`
and natural Buildkite build 202, the project deliberately simplified the
remaining ADR 0023 migration. Production-grade checkout-independent OS and
toolchain isolation was explored and proven to add disproportionate complexity
for the current lab. That work remains in Git as production-hardening reference,
but it is not an active staging dependency.

The active trust boundary begins at reviewed merged `main`. Pull requests and
non-main builds may run quality and pipeline-contract validation only. A later,
separately reviewed cutover may permit the credentialed `cml-staging` step on a
natural merged-main build. Live delivery remains independently frozen.

## Active lifecycle and authority

The merged-main controller resolves exact NetBox staging devices 6 and 7 and
their exact live homolog relationships to devices 1 and 2. It accepts only
`192.168.4.30` and `192.168.4.31`, rejects live device IDs 1/2/3 and live
management addresses `.14/.15/.20`, and loads only OpenBao roles and references
for devices 6/7. There is no live-secret fallback.

The CML boundary denies persistent brownfield lab UUID
`09605569-0468-4fc4-8684-beb5a1342b9c`. Terraform runs only the disposable
managed-pair root, admits the exact ten-resource graph, applies the exact saved
plan, uses run-isolated state, and authorizes failure cleanup only for an exact
subset of that graph. State retirement requires empty Terraform state plus
independent absence of the created staging UUID/title. Terraform never imports,
adopts, or destroys persistent live resources, and staging never invokes live
automatic rollback.

The active sequence is merged-main admission, exact NetBox resolution, exact
OpenBao 6/7 credential loading, CML admission, Terraform create, realization
verification, lifecycle start, bounded readiness, read-only NCDP planning,
exact cleanup, independent absence proof, and sanitized evidence.

## Deferred production hardening

Schema-4 ownership, root bootstrap/runtime, dedicated Unix identity, protected
Python and tools, native Mach-O closure, registration-token rotation, queue
pause, FD token supervision, LaunchDaemon migration, agent-ID binding, and
cryptographic staging attestation are deferred production-hardening
architecture. Their source and historical acceptance records remain available;
the active controller does not load their manifest or require their host model.

## Host rollback record

The unused `/private/var/db/ncdp-staging` skeleton and GID/group 420 were
removed after exact verification found no credentials, Buildkite token, tools,
runtime, source, Terraform state, LaunchDaemon, or staging process. The hidden
macOS record `ncdpstaging` / UID 420 remains inert cleanup debt after both
supported deletion mechanisms returned `eDSPermissionError -14120`. Its shell
is `/usr/bin/false`, its configured home no longer exists, it owns no active
authority, and the simplified design does not use it. No further Directory
Services workaround is authorized by this increment.

## Migration state

The repository retains `cml-staging: if: "false"` and the independent explicit
false protected-delivery guard. The legacy staging LaunchAgent remains disabled
and unloaded. This change does not run staging, re-enable the agent, or authorize
live delivery. A later cutover must first merge and validate this controller,
then make staging main-only and run one fresh natural acceptance.
