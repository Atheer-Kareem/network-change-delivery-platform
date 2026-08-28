# Phase B1-1 NetBox staging IPAM discovery acceptance

Status: discovery complete; staging address selection remains blocked pending
explicit management-prefix and external-allocation authority.

## Authority and scope

ADR 0023 and merged main
`250e406b707dc8435bb752811c10870483641ef9`, validated by natural Buildkite
Build #175, authorize identity/address/credential-separated ephemeral staging.
Phase B selected distinct staging addresses on the existing CML `System Bridge`
and reachable `192.168.4.0/24` management fabric. This is a shared L2 and failure
domain; it is not network isolation.

This increment created no staging inventory, IP assignment, credential,
Terraform state or resource, CML resource, device session, or observability
state. Its only external mutation was a temporary NetBox discovery identity,
which was retired before this record was written.

## Temporary discovery authority

NetBox `4.6.7` received one temporary user named
`ncdp-netbox-staging-discovery`, one private group, six object-constrained
permissions, and one v2 API token. The token was read-only, expired at
`2026-08-28T06:15:00.160740Z`, and was restricted to native and IPv4-mapped
container loopback. Its plaintext existed only in a mode-`0600` file under a
mode-`0700` private root outside the repository.

The permissions allowed only `view` for:

- prefix `192.168.4.0/24` if present;
- IP addresses contained by that `/24`;
- IP ranges whose start and end were contained by that `/24`;
- devices 1, 2, and 3;
- interfaces belonging to devices 1, 2, and 3; and
- site 1.

The installed Django lookup expressions were evaluated read-only before the
permissions were created. The token returned `200` for the constrained prefix,
IP-address, IP-range, device, interface, and site reads. It returned `403` for
prefix creation, IP-address creation, device modification, token creation, and
custom-field discovery. Django permission evaluation also denied prefix and IP
address add/change/delete and device change/delete. NetBox intrinsically allows
a user to administer its own API tokens, but this temporary user had an
unusable password and its API token had `write_enabled=false`; an attempted API
token creation returned `403`. No such capability was granted by the temporary
object permissions.

## IPAM result

NetBox contains **no Prefix object** for `192.168.4.0/24` and no other Prefix
object containing both canonical live addresses. Consequently there is no
authoritative prefix ID, scope, VRF/global-table declaration, VLAN, prefix
role/status, pool flag, or utilization policy to report.

Within the address space implied by the existing device primary addresses,
NetBox returned exactly three IPAddress objects and no IPRanges:

| IP object | Address | Assignment | Interface | State |
| --- | --- | --- | --- | --- |
| 1 | `192.168.4.14/24` | device 1, `core-02` | 1, `GigabitEthernet1` | active primary IPv4 |
| 3 | `192.168.4.15/24` | device 3, `core-03` | 5, `GigabitEthernet1` | active primary IPv4 |
| 2 | `192.168.4.20/24` | device 2, `edge-junos-01` | 3, `fxp0` | active primary IPv4 |

No NetBox IP range records a DHCP pool or reservation. The Mac Buildkite host
is itself attached at `192.168.4.4/24`, which is not represented by a NetBox
IPAddress object. This proves that NetBox is not currently a complete or
exclusive allocation authority for the shared LAN.

The host exposed no current DHCP lease packet or DHCP range, and no accepted
read-only router authority was available. Whether an external DHCP allocator
can issue other addresses in this `/24` is therefore unresolved.

## Address and naming decision

No Cisco or Junos staging address is proposed. Network silence cannot repair
the missing prefix and allocator authority, and candidate probing was therefore
not used to elevate any unrecorded address into authority.

The proposed names remain:

- `stg-core-02`;
- `stg-edge-junos-01`.

Neither name matched a device visible within the exact constrained discovery
set. A later authoritative creation workflow must recheck global uniqueness.

Supporting existing identifiers are:

| Object | ID | Slug |
| --- | ---: | --- |
| Lab site | 1 | `lab` |
| Cisco IOS XE platform | 1 | `cisco-ios-xe` |
| Juniper Junos platform | 2 | `juniper-junos` |
| Existing comparison role | 1 | `lab-router` |
| Management prefix | absent | not applicable |
| VLAN | absent/unresolved | not applicable |

The new staging role and ADR 0023 environment/homolog fields remain B1-2 work.

## Credential retirement and safety

After discovery, the token was disabled and returned `403`. It was then deleted
and the formerly valid bearer again returned `403`. The private token file and
directory were removed. The temporary user, group, and all six temporary
permissions were deleted. Final counts for the temporary user, group,
permissions, and token were all zero. The two existing NCDP reader tokens and
the existing `NCDP inventory read-only` permission remained present and were
not modified.

No standing B1-1 privilege remains. Increment 11A remains paused for the ADR
0023 environment migration.

## Required next authority

Before B1-2 can select or create staging addresses, a reviewed NetBox operator
increment must establish:

1. a real `192.168.4.0/24` Prefix object with explicit global/VRF, scope,
   status, role, pool/utilization, and VLAN semantics;
2. an authoritative record of gateway, infrastructure, reserved, and DHCP
   allocations; and
3. reconciliation of relevant externally allocated addresses, including the
   Buildkite host, so that NetBox and the external allocator do not both claim
   uncoordinated free space.

Only after those boundaries are accepted may a new temporary reader discover
the resulting free set and propose at least two staging address pairs.
