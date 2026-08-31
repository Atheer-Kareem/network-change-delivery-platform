# Detour B3-5 data-plane authority acceptance

## Scope and boundary

Detour B3-5 establishes exact NetBox/IPAM authority and a parallel GET-only
resolver for the future four-device data plane. It applies no network-device
configuration and changes no CML node, link, trust generation, Terraform state,
OpenBao authority, observability target, SNMP authority, protected-write
authority, or legacy v1 schema/digest.

Disposable CML staging, protected delivery, observability runtime validation,
and synthetic SNMPv3 runtime validation all remain disabled. B3-5 neither runs
nor restores those paths.

The bounded administrative migration ran against the existing loopback-only
NetBox 4.6.7 service in the `netbox-docker` project. It used one transaction,
performed no deletes, and preserved all four management primary and LIVE/STAGING
relationships. The first run reported `created=17`, `updated=21`, `reused=0`.
The independent second run reported `created=0`, `updated=0`, `reused=17`.

## Accepted NetBox identities

All prefixes are active, scoped to site ID 1 (`lab`), outside a VRF, and tagged
`ncdp-data-plane` (tag ID 9).

| Purpose | Prefix | NetBox prefix ID | VLAN association |
|---|---|---:|---|
| Data-plane parent | `10.60.0.0/16` | 2 | none |
| Core/Junos routed link | `10.60.0.0/30` | 3 | none |
| Core/transit routed link | `10.60.0.4/30` | 4 | none |
| Junos/transit routed link | `10.60.0.8/30` | 5 | none |
| USERS service | `10.60.10.0/24` | 6 | VLAN ID 1, VID 10, `USERS` |
| SERVERS service | `10.60.20.0/24` | 7 | VLAN ID 2, VID 20, `SERVERS` |
| Future router-ID/loopback pool | `10.60.255.0/24` | 8 | none |

| VLAN | NetBox VLAN ID | Site | Prefix |
|---|---:|---|---|
| VID 10 `USERS` | 1 | `lab` | prefix ID 6, `10.60.10.0/24` |
| VID 20 `SERVERS` | 2 | `lab` | prefix ID 7, `10.60.20.0/24` |

No individual router-ID/loopback, VLAN gateway, or endpoint IP address is
allocated.

## Routed interface assignments

| Logical link | NetBox IP ID/address | Device/interface | NetBox interface ID | Cable ID |
|---|---|---|---:|---:|
| Core/Junos | 17 — `10.60.0.1/30` | `core-02/GigabitEthernet4` | 11 | 1 |
| Core/Junos | 18 — `10.60.0.2/30` | `edge-junos-01/ge-0/0/0` | 12 | 1 |
| Core/transit | 19 — `10.60.0.5/30` | `core-02/GigabitEthernet2` | 2 | 2 |
| Core/transit | 20 — `10.60.0.6/30` | `transit-ios-01/GigabitEthernet0/1` | 14 | 2 |
| Junos/transit | 21 — `10.60.0.9/30` | `edge-junos-01/ge-0/0/1` | 4 | 3 |
| Junos/transit | 22 — `10.60.0.10/30` | `transit-ios-01/GigabitEthernet0/2` | 15 | 3 |

No IP object is assigned by B3-5 to `core-02/GigabitEthernet3` or
`access-sw-01/GigabitEthernet0/1` through `GigabitEthernet0/3`. Device primary
IPv4 and all management addresses remain unchanged.

## Runtime read boundary

Object permission ID 84, `NCDP data-plane read-only`, grants the normal
`ncdp-netbox-reader` user exactly the `view` action for `ipam.prefix` and
`ipam.vlan`. It has no groups and no wildcard content type. The existing token
remains non-write-enabled.

Authenticated normal API checks returned:

- VLAN collection GET: HTTP 200, exact count 2;
- prefix collection GET: HTTP 200, exact count 7;
- tagged routed IP collection GET: HTTP 200, exact count 6;
- tagged routed interface collection GET: HTTP 200, exact count 6; and
- prefix collection POST: HTTP 403, with no object created.

No token or response containing a secret was recorded.

## Resolver and compatibility evidence

`NetBoxReferenceDataPlaneProvider.resolve_reference_allocation()` accepted the
exact parent, three routed links, two VLAN services, six routed interface/IP
relationships, and router-ID pool. The resolver is GET-only and fails closed on
missing, extra, duplicate, wrong, or swapped factual objects.

Independent compatibility checks passed:

- profiled population: exact NetBox devices 1, 2, 8, and 9;
- legacy managed population: exact NetBox devices 1 and 2;
- LIVE management targets: unchanged at `.14`, `.20`, `.16`, and `.17`;
- profiled LIVE trust generation: unchanged, digest
  `sha256:06774193fc6f1b05b7cf87b62d11abbc7fbb6741f3cfef0444d0842f5cd5c305`;
- Oxidized source and trust population: exact devices 1 and 2;
- persistent observability target state: `ACTIVE`, exact count 2; and
- static SNMP and protected-write authority: exact devices 1 and 2.

B3-5 establishes authority only. The six routed IPs are not yet device running
configuration, and the VLANs are not yet deployed. VLAN, OSPF, ACL, gateway,
endpoint, and protected-delivery behavior remain later reviewed increments.
