# Profile-aware population and realization contracts

## Compatibility boundary

Detour B3-1 is repository-only. It defines additive authority contracts and
does not change any external environment or current runtime consumer.

The two inventory populations are intentionally different:

| NetBox tag | Meaning | Intended membership | Authority granted |
|---|---|---|---|
| `ncdp-managed` | Accepted legacy/v1 population | `core-02`, `edge-junos-01` | Existing v1 behavior only |
| `ncdp-profiled-inventory` | Eligibility for profiled inventory and realization | The future exact four logical devices | None by itself |

Future intended membership is exact: `core-02` and `edge-junos-01` carry both
tags; `transit-ios-01` and `access-sw-01` carry only
`ncdp-profiled-inventory`. No tag is inferred from the other.

The profiled tag grants no credential, device command, deployment, SNMP, fleet,
observability, Oxidized, or protected-write capability. Current NetBox has not
yet been migrated to this contract.
[ADR 0024](../adr/0024-two-router-live-and-ephemeral-staging.md) therefore
remains the current reference-environment truth.

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

`PersistentProfiledRealization` is a secret-free future LIVE admission model.
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
or STAGING endpoints fail validation. The new module is not imported by the
current two-node observability realization.

## CML-anchored host trust

`CmlAnchoredHostTrustRecord` and its exact four-record generation are metadata
contracts, not enrollment or a `known_hosts` renderer. A record binds:

- LIVE or STAGING realization identity and exact CML lab/node UUIDs;
- stable NetBox identity and logical device name;
- exact management address/service and profiles;
- a closed SSH public-key type and SHA256 fingerprint;
- durable CML-anchor evidence; and
- admitted time plus trust-generation identity/digest.

The trust generation rejects missing members and duplicate stable-device or CML
node identities. A fingerprint cannot be represented without its CML anchor and
stable device binding. Normal evidence deliberately has no raw public-key field.
Future private key bytes needed to render a strict `known_hosts` file are a
B3-4 private-material concern.

Trust policy remains:

- establish CML identity before considering the network-visible key;
- never accept `ssh-keyscan` or another network observation by itself;
- use no ambient user `known_hosts` as authority;
- no auto-add, blind `ssh-keygen -R`, disabled host checking, or fallback; and
- no key enrollment, replacement, or deletion in B3-1.

The later canonical LIVE trust authority will cover all four profiled devices.
Oxidized will receive an exact legacy devices-1/2 projection only after that
migration is implemented; B3-1 leaves current Oxidized trust unchanged.

## Deferred authority migration

B3-1 does not create NetBox tags, roles, platforms, types, devices, interfaces,
IPs, or cables. It allocates no address, provisions no OpenBao credential or
role, creates no CML object, changes no host trust, expands no Terraform graph,
and changes no observability or protected delivery authority. Those operations
require separately reviewed B3 increments and external acceptance evidence.

## B3-2 NetBox authority state

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
| `transit-ios-01` | 8 | planned | `transit` | present; no `ncdp-managed` | `192.168.4.16/24` | `192.168.4.31/24` |
| `access-sw-01` | 9 | planned | `access` | present; no `ncdp-managed` | `192.168.4.17/24` | `192.168.4.32/24` |

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

The new devices deliberately remain planned. Consequently, normal legacy
inventory remains exact devices 1/2, active per-device profile resolution works
for core/Junos, and `resolve_profiled_population()` still fails closed until
B3-4 supplies CML realization and host-trust acceptance and activates the IOS
members. No VLAN, prefix, OpenBao credential, CML node, device configuration,
host key, Terraform resource, Buildkite authority, or protected-write scope is
created by B3-2. ADR 0024 therefore remains current live-environment truth.

The exact mutation and independent verification evidence is recorded in the
[B3-2 acceptance record](../acceptance/profiled-netbox-inventory-detour-b3-2.md).

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
