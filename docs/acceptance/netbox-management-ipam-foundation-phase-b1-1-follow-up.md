# Phase B1-1 follow-up: management IPAM foundation acceptance

Status: external mutation complete; repository evidence pending review.

## Authority and stopping point

ADR 0023 and merged main
`65249e218eee544e1831407802dd2e7efd8a054d`, validated by natural Buildkite
Build #177, authorize this bounded follow-up to the original Phase B1-1
discovery. Phase B1-1 correctly stopped without proposing staging addresses:
NetBox then had no management Prefix and the available read-only evidence could
not establish whether an external DHCP allocator used the shared LAN.

After that discovery, the operator supplied the missing allocation authority.
The `192.168.4.0/24` CML and native-Buildkite management LAN has no DHCP server,
pool, reservation, or other dynamically managed allocation range. Allocation is
manual and static. The operator identified these occupied addresses:

| Address | Authority |
| --- | --- |
| `192.168.4.1/24` | management gateway/router infrastructure |
| `192.168.4.2/24` | CML controller/server infrastructure |
| `192.168.4.4/24` | macOS host running the native Buildkite agent |
| `192.168.4.14/24` | live `core-02` management interface |
| `192.168.4.15/24` | current `core-03` management interface |
| `192.168.4.20/24` | live `edge-junos-01` management interface |

This authority does not replace the required secondary collision and ownership
admission immediately before a future staging realization is created. This
increment does not select or reserve a staging address and does not begin B1-2.

## Fresh pre-mutation discovery

NetBox `4.6.7` contained zero Prefixes, zero IPRanges, zero VRFs, and zero IPAM
roles. It contained exactly three IPAddress objects in the prospective
management `/24`:

- ID 1, `192.168.4.14/24`, assigned to device 1 `core-02`, interface 1
  `GigabitEthernet1`;
- ID 3, `192.168.4.15/24`, assigned to device 3 `core-03`, interface 5
  `GigabitEthernet1`; and
- ID 2, `192.168.4.20/24`, assigned to device 2 `edge-junos-01`, interface 3
  `fxp0`.

There was one site, ID 1 `lab`, but no existing authority scoped the management
prefix to that site. No existing VLAN, VRF, Prefix role, or scope semantics
applied. Optional Prefix classification was therefore left unset rather than
invented.

## Bounded NetBox mutation

The established local NetBox administrative boundary executed one explicit
Django ORM transaction inside the NetBox application container. It used no API
bearer or application token, persisted no administrator credential, and did not
change any existing NCDP reader. Before saving, the transaction reasserted zero
Prefixes, zero IPRanges, and the exact three existing device assignments above.

The transaction created only:

| Type | ID | Identity | Important fields |
| --- | ---: | --- | --- |
| Prefix | 1 | `192.168.4.0/24` | active, global table, not a pool, not marked utilized, no scope, VLAN, or role |
| IPAddress | 4 | `192.168.4.1/24` | active, unassigned, gateway/router infrastructure description |
| IPAddress | 5 | `192.168.4.2/24` | active, unassigned, CML controller/server description |
| IPAddress | 6 | `192.168.4.4/24` | active, unassigned, native Buildkite macOS host description |

The Prefix description records that this is the shared CML/Buildkite
management LAN with static/manual allocation and no DHCP. No DNS name, role,
interface assignment, tenant, site scope, VLAN, VRF, IPRange, or additional
inventory object was fabricated for the infrastructure addresses.

## Independent read-back

A separate ORM process read back exactly one Prefix, zero IPRanges, six
IPAddress objects, and the same three Device objects. Prefix ID 1 was active,
global, `is_pool=false`, `mark_utilized=false`, and had no scope, VLAN, role, or
VRF. IPAddress IDs 4, 5, and 6 had the intended descriptions and remained
unassigned. Existing IPAddress IDs 1, 3, and 2 retained their exact device and
interface assignments.

Neither proposed staging device name (`stg-core-02` or
`stg-edge-junos-01`) existed. No staging IPAddress was created. The before/after
object counts changed only by one Prefix and three IPAddress objects; Device,
Interface, Site, VRF, IPAM-role, and IPRange counts did not change.

## Safety and next authority

This increment made no CML, OpenBao, Terraform, Buildkite, device,
Prometheus/Blackbox, Oxidized, AuditStore, or live-network configuration change.
It did not deactivate device 3 or alter `.15`. No temporary NetBox identity or
token was needed, so no new standing privilege exists.

After this evidence is reviewed and merged, a separate read-only increment may
use the authoritative Prefix, its explicit allocations, the operator-confirmed
static-allocation policy, and bounded secondary collision observations to
derive multiple candidate Cisco/Junos staging address pairs. Human selection
must precede B1-2 object creation. Increment 11A remains paused for the ADR 0023
migration.
