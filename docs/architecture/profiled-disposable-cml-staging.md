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

The run creates an exact-four `StagingRealizationContext`, then validates only
through its staging read-only targets and `ProfileReadOnlyAdapter`. Readiness is
profile-derived: SSH/22 for CAT8000V, IOSv, and IOSvL2; NETCONF/830 for vJunos.

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

## Failure, evidence, and recovery

The one-shot lifecycle is admit → create → start → read-only validate → eligible
destroy → independent absence proof → state retirement. It records primary and
cleanup failure separately in secret-free schema-v2 `ProfiledStagingEvidence`.
If cleanup cannot be proven, run-scoped owner-private Terraform state remains
for a guarded destroy-only recovery. Recovery validates the exact run directory,
lab/run binding, exact 17-resource state subset, and an exact-delete plan; it
never creates or starts a lab and retires state only after absence proof.

## Pipeline phase

Phase 1 restores only static Terraform format/init/validate in the quality
pipeline. The external `cml-staging` job remains absent pending controlled local
acceptance. Protected delivery remains retired; any future protected profiled
delivery requires a new design.
