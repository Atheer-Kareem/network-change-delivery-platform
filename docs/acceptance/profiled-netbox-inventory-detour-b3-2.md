# Detour B3-2 profiled NetBox inventory acceptance

## Scope and authority

Detour B3-2 moved only the local personal-lab NetBox authority toward the
four-device architecture. It did not create or change OpenBao credentials,
CML nodes, device configuration, host trust, Terraform state, Buildkite
authority, VLANs, prefixes, or protected write capability.

The ordinary NCDP token remained GET-only. Broad metadata enumeration correctly
returned HTTP 403, so the migration used the existing loopback-only NetBox
application container and NetBox administrative shell. The reviewed operator
tool validates the exact Compose project/service and `127.0.0.1:8000` listener,
runs one atomic Django transaction, performs no delete operation, and returns
only secret-free object evidence.

## Initial authority transition

Pre-migration NetBox held one active `lab` site, Cisco and Juniper
manufacturers, IOS-XE and Junos platforms, C8000V and vJunos device types, one
`lab-router` role, four NCDP tags, devices 1/2, six interfaces, four management
IP objects, no prefixes, and no cables.

The migration created:

- roles `core` (ID 3), `edge` (ID 4), `transit` (ID 5), and `access` (ID 6);
- tags `ncdp-profiled-inventory` (ID 5),
  `ncdp-management-attachment` (ID 6), `ncdp-management-live` (ID 7), and
  `ncdp-management-staging` (ID 8);
- platform `cisco-ios` (ID 3);
- device types `iosv-159-3-m12` (ID 3) and `iosvl2-2020` (ID 4);
- `core-02/GigabitEthernet4` (interface ID 11) and
  `edge-junos-01/ge-0/0/0` (interface ID 12);
- `transit-ios-01` (device ID 8), with interface IDs 13 through 16;
- `access-sw-01` (device ID 9), with interface IDs 17 through 20;
- LIVE/STAGING IP objects `.16`/`.31` (IDs 13/14) and `.17`/`.32`
  (IDs 15/16); and
- four connected cable objects.

It updated existing devices 1/2 to roles `core`/`edge`, added only the profiled
inventory tag, added the management-attachment tag without disturbing
`ncdp-protected`, and purpose-tagged their existing LIVE/STAGING IP objects.
Existing `ncdp-managed`, fleet device tags, primary IPv4 relationships, and the
fleet-interface tag on `core-02/GigabitEthernet3` were preserved.

## Accepted inventory

| Device | ID | Status | Platform/type | Management interface | LIVE / STAGING |
|---|---:|---|---|---|---|
| `core-02` | 1 | active | `cisco-ios-xe` / `c8000v` | `GigabitEthernet1` | `.14` / `.30` |
| `edge-junos-01` | 2 | active | `juniper-junos` / `vjunos-router-lab` | `fxp0` | `.20` / `.40` |
| `transit-ios-01` | 8 | planned | `cisco-ios` / `iosv-159-3-m12` | `GigabitEthernet0/0` | `.16` / `.31` |
| `access-sw-01` | 9 | planned | `cisco-ios` / `iosvl2-2020` | `GigabitEthernet0/0` | `.17` / `.32` |

Both classic IOS device types use the B2-proven operational names
`GigabitEthernet0/0` through `GigabitEthernet0/3`. Neither new device has
`ncdp-managed`.

| Cable ID | Endpoint A | Endpoint B |
|---:|---|---|
| 1 | `core-02/GigabitEthernet4` | `edge-junos-01/ge-0/0/0` |
| 2 | `core-02/GigabitEthernet2` | `transit-ios-01/GigabitEthernet0/1` |
| 3 | `edge-junos-01/ge-0/0/1` | `transit-ios-01/GigabitEthernet0/2` |
| 4 | `core-02/GigabitEthernet3` | `access-sw-01/GigabitEthernet0/1` |

The requested `.16`, `.17`, `.31`, and `.32` coordinates were absent from
NetBox before allocation and had no immediate ICMP response during the bounded
local conflict check. NetBox is now authoritative for their allocated IP object
identities and interface relationships; reachability was not used as authority.

## Verification

The second tool execution was a clean idempotency pass: zero objects created
and zero objects updated. Independent use of the ordinary read-only token then
proved:

- legacy `resolve_managed_devices()` returned only
  `netbox:dcim.device:1/core-02` and
  `netbox:dcim.device:2/edge-junos-01`;
- per-device profiled resolution passed for the two active existing devices;
- both planned IOS devices failed closed as inactive; and
- the active exact-four resolver failed closed as expected until activation.

Post-migration scheduled lifecycle evidence remained healthy:

- NetBox lifecycle reconciled `HEALTHY` with exit 0;
- Oxidized reconciled `READY`, exposed exactly `netbox-device-1` and
  `netbox-device-2`, and retained its existing trust boundary;
- observability published an `ACTIVE` exact-two target generation and fresh
  readiness; and
- Prometheus reported `probe_success=1` for core SSH and Junos NETCONF, while
  Grafana reported database health `ok`.

The historical stderr files retain older resolved failures. Their timestamps
precede the successful post-migration reconciliation records; they were not
rewritten or removed.
