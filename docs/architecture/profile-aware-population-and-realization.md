# Profile-aware population and realization contracts

## Compatibility boundary

Detour B3-1 introduced repository-only authority contracts. B3-2 through B3-5
then applied the reviewed NetBox, OpenBao, persistent CML, LIVE trust, and
data-plane IPAM boundaries without changing v1 planning or write behavior.
B4-1 adds an exact read-only routed-underlay intent/observation/assurance path.
B4-2 adds exact OSPF router-ID authority and a separate read-only OSPF vertical.
B4-3 adds exact VLAN gateway authority and a read-only router-on-a-stick/access
service vertical. None of these increments broadens a write path.

The two inventory populations are intentionally different:

| NetBox tag | Meaning | Intended membership | Authority granted |
|---|---|---|---|
| `ncdp-managed` | Accepted legacy/v1 population | `core-02`, `edge-junos-01` | Existing v1 behavior only |
| `ncdp-profiled-inventory` | Eligibility for profiled inventory and realization | The exact four logical devices | None by itself |

Current membership is exact: `core-02` and `edge-junos-01` carry both
tags; `transit-ios-01` and `access-sw-01` carry only
`ncdp-profiled-inventory`. No tag is inferred from the other.

The profiled tag grants no credential, device command, deployment, SNMP, fleet,
observability, Oxidized, or protected-write capability. B3-4 accepts the
four-device persistent LIVE realization in
[ADR 0031](../adr/0031-four-device-persistent-live-realization.md). ADR 0024
remains the historical source for the legacy exact-two runtime and dormant
Terraform staging contract.

## Exact Git-owned population

Git freezes behavior admission without inventing future NetBox object IDs:

| Stable name | Role | Platform slug | Device-type slug | NOS | Automation profile | CML realization profile |
|---|---|---|---|---|---|---|
| `core-02` | `core` | `cisco-ios-xe` | `c8000v` | `iosxe` | `cat8000v_iosxe` | `cml_cat8000v_17_18_02` |
| `edge-junos-01` | `edge` | `juniper-junos` | `vjunos-router-lab` | `junos` | `vjunos_router` | `cml_vjunos_router_23_2r1_15` |
| `transit-ios-01` | `transit` | `cisco-ios` | `iosv-159-3-m12` | `ios` | `iosv_159_3_m12` | `cml_iosv_159_3_m12` |
| `access-sw-01` | `access` | `cisco-ios` | `iosvl2-2020` | `ios` | `iosvl2_2020` | `cml_iosvl2_2020` |

Role is independently resolved factual metadata and never selects behavior.
The exact `(platform slug, device-type slug)` pair selects automation and CML
profiles through the reviewed catalog. Name and expected role then constrain
the exact population member. There is no hostname, IP-range, role, CML-state,
or generic IOS fallback.

`resolve_profiled_population()` issues GET requests only, selects the exact
profiled tag, and returns an immutable tuple in the table order. Missing,
extra, inactive, duplicated, mistagged, or mismatched members fail closed.
Per-device profiled resolution uses the same tag and the same name-to-facts
catalog check: a name outside the exact four, or an admitted name with mismatched
role, platform, device type, NOS, automation profile, or CML profile, fails
closed. It has no `ncdp-managed` fallback.

## LIVE and STAGING projection

Normal code can project only:

```text
ProfiledInventoryDevice.live_read_only_target()
```

There is no device method accepting a purpose and no device-owned STAGING
projection. A STAGING target can be produced only by:

```text
StagingRealizationContext.staging_read_only_target(profiled_device)
```

The context must be `READY`, fresh, and bound to one staging run and CML lab.
It contains the exact four logical devices. Each device binding carries the
stable NetBox identity, exact automation and CML profiles, exact CML node UUID,
the explicit NetBox STAGING endpoint, identical physical/L3 management
interface identities, and typed readiness and trust evidence references.

Projection requires equality with the profiled device's STAGING IP-object
identity, numeric address, interfaces, name, stable device identity, and
profiles. The target is built from that admitted binding. It never calls the
LIVE method, reads `primary_ip4`, accepts arbitrary address input, or remains
usable after the context leaves `READY` or expires.

Lifecycle state is deliberately small: `PREPARING`, `READY`, `CLEANING`,
`RETIRED`, `FAILED`, and `AMBIGUOUS`. This is a projection gate, not a workflow
engine. B3-1 performs no actual staging target execution.

## Persistent realization admission

`PersistentProfiledRealization` is the secret-free LIVE admission model.
It binds:

- one stable realization and CML lab identity;
- lifecycle state, aware admission/expiration timestamps, and durable evidence;
- exactly four Git-approved logical names in canonical order;
- unique stable NetBox device and CML node identities;
- exact role, automation profile, and CML realization profile pairing; and
- explicit LIVE management IP identity/address, service, physical attachment,
  and L3 owner.

It contains no CML client or mutation method. Missing or extra members,
duplicate identities, wrong profile pairs, cross-device management bindings,
or STAGING endpoints fail validation. The observability runtime retains a
separate exact-two target projection while admitting the exact four-node CML
population; it does not consume this model as target inventory.

## CML-anchored host trust

`CmlAnchoredHostTrustRecord` and its exact four-record generation are the
secret-free evidence contracts used by the private B3-4 enrollment path. A
record binds:

- LIVE or STAGING realization identity and exact CML lab/node UUIDs;
- stable NetBox identity and logical device name;
- exact management address/service and profiles;
- a closed SSH public-key type and SHA256 fingerprint;
- durable CML-anchor evidence; and
- admitted time plus trust-generation identity/digest.

The trust generation rejects missing members and duplicate stable-device or CML
node identities. A fingerprint cannot be represented without its CML anchor and
stable device binding. Normal evidence deliberately has no raw public-key field.
Public key bytes needed by SSH remain only in the private exact-four
`known_hosts` rendering. They do not enter normal evidence or the repository.

Trust policy remains:

- establish CML identity before considering the network-visible key;
- never accept `ssh-keyscan` or another network observation by itself;
- use no ambient user `known_hosts` as authority;
- no auto-add, blind `ssh-keygen -R`, disabled host checking, or fallback; and
- atomic publication of only the exact CML-anchored generation.

The canonical profiled LIVE trust authority covers all four profiled devices.
Oxidized remains on its independent exact devices-1/2 trust projection; B3-4
does not widen its runtime population. When the Junos CML node was replaced,
that exact-two trust was freshly CML-anchored to the new node UUID as required
by ADR 0020. The observed key bytes remained the same, but realization-bound
metadata was republished.

## Deferred authority migration

B3-1 does not create NetBox tags, roles, platforms, types, devices, interfaces,
IPs, or cables. It allocates no address, provisions no OpenBao credential or
role, creates no CML object, changes no host trust, expands no Terraform graph,
and changes no observability or protected delivery authority. Those operations
require separately reviewed B3 increments and external acceptance evidence.

## NetBox authority state through B3-5

Detour B3-2 migrates only the local NetBox authority. The reviewed,
no-delete operator tool is
[`migrate_b3_inventory.py`](../../scripts/netbox/migrate_b3_inventory.py). It
uses the existing local NetBox administrative shell rather than widening the
normal GET-only token. It inspects exact objects before reuse or creation,
applies the bounded change in one database transaction, rejects conflicting
identity, assignment, or cable state, and verifies the final population before
commit. A second execution must report no created or updated objects.

NetBox now assigns these stable identities and management relationships:

| Device | NetBox ID | Status | Role | Profile tag | LIVE | STAGING |
|---|---:|---|---|---|---|---|
| `core-02` | 1 | active | `core` | present with legacy tags preserved | `192.168.4.14/24` | `192.168.4.30/24` |
| `edge-junos-01` | 2 | active | `edge` | present with legacy tags preserved | `192.168.4.20/24` | `192.168.4.40/24` |
| `transit-ios-01` | 8 | active | `transit` | present; no `ncdp-managed` | `192.168.4.16/24` | `192.168.4.31/24` |
| `access-sw-01` | 9 | active | `access` | present; no `ncdp-managed` | `192.168.4.17/24` | `192.168.4.32/24` |

The two IOS devices use exact operational interfaces
`GigabitEthernet0/0` through `GigabitEthernet0/3`. Their physical and L3
management owner is `GigabitEthernet0/0`, tagged both
`ncdp-management-attachment` and `ncdp-protected`. The LIVE address is each
device's primary IPv4; the distinct STAGING address is explicit and non-primary.

NetBox cable IDs 1 through 4 record the approved physical topology:

- `core-02/GigabitEthernet4` to `edge-junos-01/ge-0/0/0`;
- `core-02/GigabitEthernet2` to
  `transit-ios-01/GigabitEthernet0/1`;
- `edge-junos-01/ge-0/0/1` to
  `transit-ios-01/GigabitEthernet0/2`; and
- `core-02/GigabitEthernet3` to
  `access-sw-01/GigabitEthernet0/1`.

B3-2 deliberately left the new devices planned. B3-4 activated them only after
the exact persistent CML realization, management readiness, credentials, and
CML-anchored trust passed. Normal legacy inventory remains exact devices 1/2,
while `resolve_profiled_population()` now returns exact devices 1/2/8/9.

The exact mutation and independent verification evidence is recorded in the
[B3-2 acceptance record](../acceptance/profiled-netbox-inventory-detour-b3-2.md).

### Exact data-plane authority

B3-5 adds the exact `10.60.0.0/16` reference allocation to NetBox without
changing any running network configuration. The `ncdp-data-plane` tag provides
visibility over the exact seven prefix, two VLAN, six routed-interface, and six
routed-IP populations; tag membership alone is never admission authority.

`NetBoxReferenceDataPlaneProvider.resolve_reference_allocation()` is a separate
GET-only profiled resolver. It compares every factual NetBox identity and value
with one closed Git-owned topology catalog: parent and child prefixes, VLAN IDs
and canonical names, VLAN-prefix relationships, stable device/interface and
cable identities, and exact routed IP assignments. Missing, extra, duplicate,
wrong, or swapped objects fail closed. It does not feed v1 planning or device
execution and exposes no IPAM write method.

The normal `ncdp-netbox-reader` identity has a dedicated `view`-only object
permission for `ipam.prefix` and `ipam.vlan`. Its token remains non-write-enabled,
and an authenticated API write remains denied. The bounded administrative
writer is the no-delete, transactional
[`migrate_b3_data_plane.py`](../../scripts/netbox/migrate_b3_data_plane.py)
operator. A second run must make zero effective changes.

NetBox now owns the exact routed link addresses and VLAN/prefix identities.
Git owns only how those resolved facts will participate in later routing,
switching, and security verticals. B3-5 allocates no loopback address, VLAN
gateway, or endpoint address and applies no data-plane configuration to a
device. Exact IDs and verification evidence are in the
[B3-5 acceptance record](../acceptance/data-plane-authority-detour-b3-5.md).

## B4-1 routed-underlay read-only path

The first managed service vertical consumes, rather than duplicates,
`ReferenceDataPlaneAllocation`. `RoutedUnderlayIntent` binds the exact three
links and six interface/IP identities to admin-up intent. Its
`ManagedOwnershipEnvelope` owns only routed L3 presence, exact address/prefix,
and admin-enabled state on stable interfaces belonging to devices 1, 2, and 8.
`access-sw-01`, all management interfaces, and every VLAN/OSPF/ACL property are
outside the envelope.

Current O is collected through exact profiled LIVE targets and the existing
collection-only adapters. The vendor-independent D1 digest excludes rendered
text. IOS XE, classic IOS, and Junos change renderings are deterministic O-to-D1
artifacts: they remove only addresses in the routed-underlay envelope and add
the desired addresses. A separate final-state renderer builds the clean D1-only
Batfish candidate. Neither path nor `ProfileReadOnlyAdapter` exposes execution.
Offline Batfish assurance uses an exact-four snapshot so that `access-sw-01`
exclusion is positively checked rather than assumed. D0 persistence and live
application remain deferred.

## B4-2 OSPF read-only path

The OSPF population is exact devices 1, 2, and 8. A separate GET-only routing
identity resolver admits exactly NetBox IP-address IDs 23–25 from prefix ID 8;
they remain unassigned, non-primary router IDs rather than loopback addresses.
`ProfileOspfReadOnlyAdapter` dispatches only IOS-XE, IOS, and Junos profiles and
has no write surface; the access profile fails closed.

Observation owns only process/router-ID and the six admitted interface facts.
Transition rendering binds O and the independent OSPF D1. Final-state Batfish
assurance composes unchanged routed-underlay D1 with OSPF D1 and does not import
live NetBox, OpenBao, CML, or device access into PR assurance.

## B4-3 VLAN read-only path

`ReferenceVlanServiceAllocation` binds VLANs 10/20 and prefixes 6/7 to core
parent interface ID 7, planned subinterfaces 21/22, gateway IPs 26/27, access
interfaces 18–20, and cable 4. The normal provider is GET-only; the accepted
offline reconstruction is PR evidence rather than a replacement for NetBox.

`ProfileVlanReadOnlyAdapter` admits only `core-02` IOS-XE and `access-sw-01`
IOSvL2. It observes the exact managed parent, subinterfaces, VLAN database,
trunk, access ports, and relevant SVI conflicts through strict read-only
transports. Transition rendering binds real O to the independent VLAN D1 and
has no execution surface.

The active offline Batfish model distinguishes four managed network nodes from
two supplemental assurance-only hosts. The fixtures and their synthetic `.100`
coordinates do not enter profiled inventory, NetBox authority, ownership
envelopes, CML, OpenBao, or delivery targets. Four infrastructure edges remain
accepted physical truth; two synthetic fixture edges exist only in Batfish.

## B3-3 OpenBao and pipeline state

OpenBao now holds exact stable-ID SSH paths for NetBox devices 1, 2, 8, and 9.
The existing five-minute, single-use `ncdp-personal-lab` AppRole reads those
four paths through one exact policy with no wildcard. The provider derives the
path from stable NetBox identity for either legacy or profiled inventory; name,
hostname, role, profile, and management address cannot select a credential.

Buildkite staging identity is prepared with four separate exact-path policies
and JWT roles. Protected live deployment and SNMP authority remain their prior
devices 1/2 only. Because the current Terraform staging realization is still
two-device, B3-3 comments out automatic `cml-staging` and the complete protected
delivery group together. Quality, Terraform static validation, and PR Batfish
remain active. Restore both paused blocks together only when the operator
explicitly decides disposable CML staging is useful again and its Terraform
topology is ready for the intended profiled population; no CML feature or
historical evidence is removed.

The [B3-3 acceptance record](../acceptance/profiled-openbao-onboarding-detour-b3-3.md)
contains the secret-free applied-state evidence.

## B3-4 persistent LIVE state

The operator-owned `NCDP Live` lab now contains two infrastructure nodes and
the exact four profiled devices. It remains outside Terraform. The physical
data-plane links match NetBox cables 1 through 4, while each management
interface attaches to the existing management switch. No VLAN, OSPF, ACL, or
endpoint configuration is introduced.

The new IOS bootstrap path reads only the exact OpenBao credentials for stable
NetBox devices 8 and 9, derives IOS type-9 scrypt verifiers in memory, and stores
no plaintext password in CML configuration or evidence. `access-sw-01` uses
routed `GigabitEthernet0/0` with `no switchport` for independent management.

The exact-four private LIVE trust generation is CML-anchored before network key
observation and is published atomically outside the repository. It is the trust
input for four real `ProfileReadOnlyAdapter` PASS results. Ambient user trust,
Oxidized trust, auto-add, fallback, and algorithm relaxation are not used.

The existing vJunos image required the explicitly authorized wipe/delete/
recreate workaround after reboot failed to reapply stored Day-0. The replacement
retains stable NetBox/logical identity and accepted configuration but has a new
CML node UUID. The exact identities, topology, fingerprints, and read-only
results are in the
[B3-4 acceptance record](../acceptance/persistent-profiled-live-realization-detour-b3-4.md).

Observability admits the exact four-device persistent CML population but still
projects only the legacy `ncdp-managed` devices 1/2. Oxidized, SNMP, v1 fleet,
and protected write authority likewise remain exact-two. Automatic disposable
CML and protected delivery remain paused, and the Terraform staging topology is
unchanged. Buildkite observability runtime and synthetic SNMPv3 runtime checks
are separately paused until explicit operator decisions integrate them with the
expanded profiled topology; the implementations remain intact.
