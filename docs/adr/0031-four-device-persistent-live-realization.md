# ADR 0031: Four-device persistent LIVE realization

- Status: Accepted
- Date: 2026-08-31
- Supersedes: ADR 0024 for persistent `NCDP Live` environment truth only

## Context

ADR 0024 accepted a persistent two-router CML lab and a separate disposable
two-router Terraform realization. Detour B1 through B3-3 established an
additive four-device profile model, exact NetBox authority, credentials keyed by
stable NetBox device ID, and a profile-aware read-only adapter without widening
the legacy write path.

The persistent lab can now realize the four approved logical devices. This
decision must not imply that legacy delivery, Oxidized, observability, SNMP, or
the dormant disposable Terraform topology has also become four-device.

During realization, the existing vJunos node exhibited the accepted image
behavior in which reboot did not reapply its stored Day-0 configuration. After
explicit operator authorization, the old node was wiped, deleted, and recreated
from the preserved Day-0 configuration. Stable NetBox and logical identity did
not change, but CML realization identity did.

## Decision

The operator-owned persistent lab remains `NCDP Live`, UUID
`09605569-0468-4fc4-8684-beb5a1342b9c`, outside Terraform. Its exact profiled
LIVE population is:

| Logical device | NetBox ID | CML node UUID | Profile | LIVE management |
|---|---:|---|---|---|
| `core-02` | 1 | `59fc118d-dfa3-4a45-a905-6a056b591550` | `cat8000v_iosxe` | `192.168.4.14:22` |
| `edge-junos-01` | 2 | `3ee87d9c-09b5-4ed2-a655-092bf89b1190` | `vjunos_router` | `192.168.4.20:830` |
| `transit-ios-01` | 8 | `b6a5e482-a867-4b88-addc-02eb068afb84` | `iosv_159_3_m12` | `192.168.4.16:22` |
| `access-sw-01` | 9 | `fee01570-a8c6-478c-9e29-ebb991335346` | `iosvl2_2020` | `192.168.4.17:22` |

The lab contains those four managed nodes plus the existing external connector
and management switch. It has the four NetBox-authoritative data-plane cables
and four management attachments. No VLAN, OSPF, ACL, endpoint, or other
data-plane configuration is accepted by this decision.

After acceptance, all four CML node UUIDs are frozen realization identity.
Missing or different profiled nodes fail closed rather than being silently
recreated. Any later replacement requires the same explicit operator review,
reconciliation, trust generation, and acceptance used for the Junos exception.

IOS bootstrap consumes credentials transiently from the exact OpenBao paths for
NetBox devices 8 and 9. Durable CML configuration contains an IOS type-9 scrypt
verifier, not a plaintext password. The new devices remain absent from
`ncdp-managed` and become active only after management readiness, exact
CML-anchored trust, and real profile-adapter acceptance pass.

Profile-aware LIVE trust is a separate private exact-four generation. Each
record binds the network-visible key to the exact CML lab/node, CML-controlled
hostname/address evidence, stable NetBox device, management endpoint, automation
profile, and realization profile. Ambient user trust, network-only discovery,
auto-add, fallback, disabled host checking, and algorithm relaxation are not
authority. Oxidized remains an exact devices-1/2 projection. Replacement of the
Junos CML node requires fresh exact-two CML-anchored enrollment: its unchanged
key bytes are rebound to the new realization UUID in Oxidized trust metadata,
without admitting devices 8/9.

The legacy `ncdp-managed` inventory, v1 planning/write schema, Oxidized,
management-service target population, SNMP authority, and protected deployment
authority remain exact devices 1 and 2. Observability admits the exact
four-device CML population but projects only its existing two management
targets. This is an explicit compatibility projection, not implicit partial
inventory.

Automatic disposable CML staging and protected delivery remain paused. The
Terraform staging graph is not changed by B3-4. Restore both only by explicit
operator decision after the intended profiled topology is ready.

## ADR 0024 relationship

This ADR supersedes ADR 0024 only where it describes the persistent LIVE lab as
two-router. ADR 0024 remains historical accepted truth and still describes the
legacy exact-two runtime boundary and the currently disabled two-router
Terraform staging implementation. No four-device STAGING realization or
STAGING adapter acceptance is claimed here.

## Consequences

The personal lab has four stable profile-aware managed network-device identities
and a corresponding persistent physical CML realization. All four can be
resolved from NetBox, credentialed from OpenBao by stable ID, verified through
strict realization-bound trust, and collected through the read-only profile
adapter.

Classic IOS remains outside `InventoryDevice` and outside all current write
authority. Later increments separately own service intent, managed drift,
disposable staging, and protected multi-device delivery.
