# Profiled exact-four disposable CML staging

Status: implemented in source; pending one separately authorized controlled local
create, validate, and destroy acceptance. It is not yet an active Buildkite job.

## Purpose and authority

Disposable staging is the real-platform, credentialed, strict-trust, read-only
integration counterpart to four-device Batfish assurance. It is not protected
delivery, a deployment authority, a schema-v1 restoration, a B5 acceptance
path, or candidate configuration application. The sole current configuration
write surface remains local `ncdp profiled-deploy` for its admitted operation.

Its population is resolved only through `NetBoxProfileInventoryProvider` and
`ncdp-profiled-inventory`: core-02 (CAT8000V IOS-XE), edge-junos-01 (vJunos),
transit-ios-01 (IOSv), and access-sw-01 (IOSvL2). The profile catalog projects
node definitions, images, device-side ports, readiness services, and CML
resource policy. No `ncdp-managed`, `InventoryDevice`, legacy inventory
provider, multivendor adapter, planning function, or write adapter participates.

## Disposable realization

One run creates `NCDP Staging <run-id>` with exactly six nodes, nine links, and
17 Terraform-managed resources: a CML lab, system bridge, unmanaged management
switch, four profiled device nodes, nine links, and one lifecycle resource.
Day-0 is management-only and derives each STAGING endpoint from NetBox. It sets
host identity and profile-appropriate management access, including Junos
NETCONF, but deliberately excludes underlay, OSPF, VLAN/trunk, ACL, SNMP, and
interface-description intent. The historical 10.6.12.0/30 bootstrap is absent.

Before Terraform can create anything, authenticated GET-only CML admission
rejects any existing lab whose title starts with `NCDP Staging` and any active
fixed STAGING management endpoint. After creation, Terraform outputs are only
claims: independent CML GET observations must prove the exact lab UUID/title,
six node UUIDs and profile definitions/images, nine link UUIDs and device-side
slots, and the bounded management-only stored Day-0. The resulting topology
evidence digest binds those observed run-specific UUIDs and relationships.

The run first creates an exact-four PREPARING `StagingRealizationContext`, then
establishes trust and validates a new READY context. A READY context is invalid
if any trust reference is absent. Validation uses only its staging read-only
targets and `ProfileReadOnlyAdapter`. Readiness is profile-derived: SSH/22 for
CAT8000V, IOSv, and IOSvL2; NETCONF/830 for vJunos. Each readiness reference
binds the run, lab/node UUID, stable identity, endpoint, service, result, and
actual bounded elapsed duration. Read-only collection rechecks the exact
hostname, management interface and STAGING address; IOSv and IOSvL2 also require
their normalized Gi0/0..Gi0/3 physical realization.

## Credentials and trust

The future Buildkite execution boundary uses `BuildkiteStagingSecretProvider`:
one device-scoped OpenBao JWT login/read for each of stable device IDs 1, 2, 8,
and 9. Broad ambient AppRole, NetBox, CML, or device credentials are rejected.
Terraform bootstrap inputs are sensitive; Cisco Day-0 uses an IOS verifier and
Junos uses an encrypted password representation.

Each run creates a private, create-only staging trust root. Its exact-four host
trust records bind the run, lab UUID, CML node UUID, stable identity, logical
name, automation/CML profile, STAGING endpoint, and profile service. Ambient
known-hosts, auto-add, fallback trust, and relaxed algorithms are prohibited.
Server keys come from three bounded direct Paramiko handshakes per endpoint;
algorithm and fingerprint must be stable across all samples and belong to the
closed host-key algorithm contract. The trust records consume the independently
observed CML anchors rather than self-asserted Terraform identifiers. NETCONF
entries use the exact `[host]:830` known-hosts form.

## Failure, evidence, and recovery

The one-shot lifecycle is admit → create → fenced saved START plan → read-only
validate → fenced saved destroy plan → independent absence proof → state
retirement. Cleanup authority derives from a nonempty known Terraform state,
not from a returned READY context, so partial apply, start, readiness, CML
admission, trust, context, and read-only failures remain cleanup-eligible. A
normal successful realization requires the exact 17-address state and 17 exact
deletes. Failed partial creation permits only a nonempty subset of those same
addresses and an exactly matching delete-only plan; unknown or empty state is
never destructive authority.

Before create, the run stores one owner-only mode-0600
`recovery-inputs.tfvars.json` containing the exact admitted Terraform inputs.
It contains derived password verifiers, never plaintext passwords or OpenBao
session material. Normal operations and guarded recovery use those same bytes.
Recovery therefore needs no OpenBao access; it validates directory ownership,
input/state/lab binding, the known resource subset, and a saved exact-delete
plan. It cannot create or start, and state, backup, plans, and recovery inputs
are retired only after independent CML absence is proven.

Schema-v2 `ProfiledStagingEvidence` preserves source commit, observed lab and
run-specific topology, final READY context digest, actual trust generation,
per-device readiness and read-only facts, create/start/destroy/absence/state
retirement, and separate primary/cleanup failures. An uncertain Terraform
mutation is never replayed: known owned state may proceed only to bounded
cleanup, while unprovable ownership is `AMBIGUOUS` and retained for review.

## Pipeline phase

Phase 1 restores only static Terraform format/init/validate in the quality
pipeline. The external `cml-staging` job remains absent pending controlled local
acceptance. Protected delivery remains retired; any future protected profiled
delivery requires a new design.
