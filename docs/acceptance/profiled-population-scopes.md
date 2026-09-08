# Profiled population scopes acceptance

## Acceptance and evidence boundary

**CAP-POPULATION-SCOPES — ACCEPTED.** The user explicitly accepted the merged
implementation and controlled runtime evidence after review. This is user
sign-off, not acceptance inferred from passing tests. The
[capability ledger](../roadmap.md#cap-population-scopes--population-derived-admission-and-realization)
is authoritative for state; the [population scope contract](../architecture/population-scopes.md)
defines behavior.

Implementation merged through [PR #149](https://github.com/Atheer-Kareem/network-change-delivery-platform/pull/149).
Acceptance used clean `main`, equal to `origin/main`, at
`adb7532a0a52e07642d0aad1934b8f5e2cc20e1b`.
This record preserves the reviewed acceptance-session evidence; no runtime
operation was repeated for this documentation closeout.

CAP-POPULATION-SCOPES is accepted. The real Git-declared population resolves
before exact consumer projection; LIVE physical realization/trust, Oxidized,
observability and disposable CML staging operate against explicit reviewed
scopes. Merged synthetic tests independently prove variable 1/2/4/5-member
populations, repeated-profile instances and service-scope isolation. Managed
membership grants no write authority, and current production promotion,
credential and operation-admission boundaries remain unchanged.

Runtime preservation of the four-device lab plus merged synthetic
variable-cardinality proof establishes the capability. A fifth real device is
not required for acceptance.

## Merged implementation proof

- Git declares the exact ordered managed population. Bounded
  `ProfiledLogicalName` replaces the four-instance enum; immutable consumer
  scopes bind exact selected facts and exclude unrelated managed members from
  their intrinsic identity.
- Complete managed-population resolution precedes consumer projection. Missing,
  extra, inactive, duplicate or mismatched members fail closed. Multiple
  instances may reuse an existing profile; automation and CML profile
  vocabularies remain closed.
- LIVE/STAGING realization and trust, Oxidized and observability require exact
  caller-owned scopes. Routed-underlay, OSPF, VLAN and ACL retain bounded service
  subjects. SNMP remains a profile-capability intersection.
- Staging ownership/counts derive from N devices and L data links: N+2 nodes,
  N+L+1 links and 2N+L+5 Terraform resources. IOSv recycle is realization-profile
  policy, not instance-name behavior. Current staging evidence is schema v3;
  historical v2 retains its original meaning and reader.
- Scoped observability contracts are `TargetGeneration v3`,
  `RealizationAdmission v4` and `ObservabilityReady v3`.
- Full LIVE admission compares exact physical interface endpoint pairs.
  Membership and read-only scopes grant no operation or write authority; fixed
  promotion and write admission were not expanded.

Merged synthetic coverage proves 1-, 2-, current 4- and 5-member populations,
repeated instances of the same existing profile, unchanged bounded service
scope when an unrelated managed member is added, and rejection of attempts to
derive write authority from population/read-only scopes.

Final implementation validation: full local pytest **2,458 passed, 5 skipped**;
Docker quality **2,416 passed, 47 skipped**; actual isolated observability runtime
validation and Terraform validation **PASS**. Ruff, format, diff, package,
Ansible, static Buildkite and Markdown gates passed. Acceptance-session focused
regressions additionally passed **104 population/staging/compatibility tests**
and **21 planning/write-admission tests**. These results were not rerun as a
runtime suite for this closeout.

## Real managed population and consumer scopes

The GET-only NetBox resolver admitted this unchanged canonical order:

| Stable identity | Logical name | Automation profile |
|---|---|---|
| `netbox:dcim.device:1` | `core-02` | `cat8000v_iosxe` |
| `netbox:dcim.device:2` | `edge-junos-01` | `vjunos_router` |
| `netbox:dcim.device:8` | `transit-ios-01` | `iosv_159_3_m12` |
| `netbox:dcim.device:9` | `access-sw-01` | `iosvl2_2020` |

Role, platform, device type, automation/CML profiles, LIVE/STAGING management
bindings and protected-interface facts remained unchanged and validated.

| Runtime consumer scope | Members |
|---|---:|
| LIVE realization | 4 |
| STAGING realization | 4 |
| Oxidized collection | 4 |
| Observability | 4 |
| Routed-underlay | 3 |
| OSPF | 3 |
| VLAN | 2 |
| ACL | 1 |

The SNMP capability projection remained exactly devices **1 and 2**.

## Existing LIVE realization and trust

`CURRENT_LIVE_REALIZATION` passed read-only admission of the persistent
`NCDP Live` lab: exact **six nodes and nine links**, reviewed node identities
and images, and all managed devices BOOTED. No persistent CML mutation occurred.

| Management fabric endpoint | Reviewed peer |
|---|---|
| External connector slot 0 | Management-switch slot 3 |
| Management-switch slot 4 | core-02 slot 0 / GigabitEthernet1 |
| Management-switch slot 5 | edge-junos-01 slot 0 / fxp0 |
| Management-switch slot 6 | transit-ios-01 slot 0 / GigabitEthernet0/0 |
| Management-switch slot 7 | access-sw-01 slot 0 / GigabitEthernet0/0 |

Exact data links verified: core slot 3 ↔ Junos slot 1; core slot 1 ↔ transit
slot 1; Junos slot 2 ↔ transit slot 2; core slot 2 ↔ access slot 1.

LIVE host trust validated exactly four records, current CML anchors, management
endpoints, fingerprints and digest. Existing trust remained unchanged, with no
reenrollment, ambient fallback or auto-add.

## Reviewed runtime reconciliation

Only the existing reviewed updater/admission mechanisms were used.

| Installed runtime | Before source | After source |
|---|---|---|
| Oxidized | `77b5a768ba259e99e02866d525819bf73b05f4d0` | `adb7532a0a52e07642d0aad1934b8f5e2cc20e1b` |
| Observability | `8ad9084b8e7a37fdafd5daa3497942d19d38637b` | `adb7532a0a52e07642d0aad1934b8f5e2cc20e1b` |

The [Oxidized updater](../../scripts/oxidized/update_service_runtime.sh) and
normal reconciliation produced **READY**, with verified container, fresh
readiness and valid host-trust digest. `/nodes.json` contained exactly
`netbox-device-1`, `netbox-device-2`, `netbox-device-8` and `netbox-device-9`,
all in group `managed`.

Routine ephemeral Oxidized source SecretID issuance: **YES**. Persistent
credential rotation/reissuance: **NO**. No OpenBao role or policy changed.

The [observability updater](../../scripts/observability/update_service_runtime.sh)
and supported [read-only admission command](../../scripts/observability/admit_cml_realization.py)
reconciled the installed service. Previous short-lived realization evidence was
schema v2; fresh evidence replaced it through supported reconciliation, without
reinterpreting old bytes in place. `RealizationAdmission v4`,
`TargetGeneration v3` and `ObservabilityReady v3` validated.

Prometheus/Blackbox health and exact target membership passed. All four real
probes succeeded: core-02 SSH/22, edge-junos-01 NETCONF/830, transit-ios-01
SSH/22 and access-sw-01 SSH/22.

## Main build and disposable staging

| Build correlation | Value |
|---|---|
| Build | [435](https://buildkite.com/atheer-kareem/network-change-delivery-platform/builds/435) |
| Build UUID | `01a080af-9bf3-45ab-89f3-6ac7f0d88f78` |
| Commit | `adb7532a0a52e07642d0aad1934b8f5e2cc20e1b` |
| Branch/source | `main`; existing naturally created webhook build |

No duplicate build was triggered. Engineering stages, Batfish and real
disposable CML staging passed. Planning and the promotion/decision step passed;
core-02 was already compliant and no deployment plan was required. This did not
exercise a deployment promotion or write. Human authorization continuation was
**NO**; the block and downstream deployment remained blocked. No LIVE deployment
occurred.

Current schema-v3 staging evidence established:

- Exact scope **4 devices**, readiness **4/4**, read-only validation **4/4**.
- Only `transit-ios-01` required recycle, successful once: first BOOTED →
  **60.197-second persistence hold** → STOP → START → second BOOTED.
- Derived graph: **6 nodes, 9 links, 17 Terraform resources**.
- Cleanup, independent absence verification and Terraform state retirement:
  **succeeded**. No device CLI write occurred in staging.

Exact retained staging artifact-byte digest:

`sha256:c343b2a941f8dcad7539f9a7e109f848b60a21188ef11c33b266d18ba7434dcd`

Stable reviewed staging topology-contract digest:

`sha256:764405fa9a44d7c42ae402ec2fa1d03c2b7dd9ba0916954e03c7a7d5baf68064`

Run-specific staging evidence `topology_digest`:

`sha256:9dff20477969767125a34238e8597e865bddd2e908693e87e7dee9278cf26548`

These topology digests have different contracts. The first identifies the
stable reviewed topology definition; the second binds the actual run's CML
identities and endpoints. Their differing values are expected and do not
indicate topology drift; the run-specific meaning predates this capability.

Artifact API download permission was unavailable. Verification instead used the
retained exact JSON, validated through the current typed schema and same-build
success predicate, and matched its exact byte hash to Buildkite success
metadata. This record does not claim a direct API artifact download.

## Preserved authority and historical evidence

Device configuration writes: **ZERO**. Human continuation: **NO**. The current
promotion target remains `core-02` / `netbox:dcim.device:1`. IOSv and IOSvL2
interface-description write admission remains denied. Population membership
cannot mint promotion; observability, Oxidized, trust and staging scopes cannot
grant write authority. No new deploy credential path or OpenBao role/policy
broadening occurred. NetBox and persistent CML topology were not mutated.
Only authorized service reconciliation and normal disposable staging ran.

Historical staging schema v2 remains readable; current runtime emitted v3.
Historical Terraform state was not migrated, and historical ADRs/acceptance
records were not rewritten. AuditStore stayed at **11 historical records,
1 profiled record and 0 chronology children**. All **62 checked file hashes**
remained unchanged. No acceptance evidence was fabricated or credential value
exposed.

Generic intent and broader promotion-target selection remain
`CAP-INTENT-DELIVERY`; IOSv/IOSvL2 write admission remains
`CAP-PROFILE-REUSE-WRITE`; multi-target execution remains `CAP-PROFILED-ROLLOUT`.
Operation-bound assurance remains deferred under `CAP-OP-ASSURANCE`. None is
implemented by this acceptance closeout. The temporary PR/development CML
exception remains **ACTIVE**.
