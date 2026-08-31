# Detour B4-2 OSPF triangle acceptance

## Authority and scope

B4-2 allocates three NetBox-owned routing identities and prepares a proposed
OSPF service over the accepted B4-1 routed underlay. It does not apply OSPF or
underlay configuration to a network device.

The idempotent NetBox migration created tag `ncdp-routing-identity` (ID `10`)
and these active, unassigned, non-primary IP-address objects inside prefix ID
`8` (`10.60.255.0/24`):

| Stable device | Router ID | NetBox IP ID |
|---|---|---:|
| `core-02` / device 1 | `10.60.255.1/32` | 23 |
| `edge-junos-01` / device 2 | `10.60.255.2/32` | 24 |
| `transit-ios-01` / device 8 | `10.60.255.3/32` | 25 |

The second migration run made zero effective changes. Device 9 has no routing
identity. The six `ncdp-data-plane` routed IP objects remain exactly IDs 17–22,
and management/primary relationships are unchanged. Normal application access
remains GET-only.

The accepted routing-identity allocation digest is
`sha256:7e57aaa1dd066fecadb2e43d1f1f82a32cf2250648ddd656d7f0068194d4b7ca`.
The B3-5 reference allocation digest remains
`sha256:1352521feec8f787eb1a468c586dd3390428289314c3984416ab987a8af61b3d`.

These `/32` objects are router-ID authority only. They are not assigned to
interfaces, configured as loopbacks, advertised routes, primary addresses, or
reachability targets.

## Real observed state O

At `2026-08-31T12:16:44.441475Z`, the normal stable-ID
`OpenBaoSecretProvider`, exact profiled LIVE trust, and read-only profile
transports observed OSPF absent on all three routers:

| Router | Process/router ID | Managed interfaces |
|---|---|---|
| `core-02` | absent / none | `GigabitEthernet4`, `GigabitEthernet2`: not participating |
| `edge-junos-01` | absent / none | `ge-0/0/0`, `ge-0/0/1`: not participating |
| `transit-ios-01` | absent / none | `GigabitEthernet0/1`, `GigabitEthernet0/2`: not participating |

The normalized managed-O digest is
`sha256:845472fbdedb75712fea0dbcea68dc19d13034316d1fe014fc3a8c7aebc33e98`.
A fresh bounded personal-lab AppRole SecretID was issued for this read-only run
and destroyed immediately afterward. No token, credential, or raw provider
artifact entered evidence.

## Proposed D1 and transition render

The vendor-independent OSPF D1 digest is
`sha256:55f5718089228eb4e9f3badebca036135461c10b3c4312184462b5468d463182`.
It owns only process presence, the exact NetBox router IDs, exact six interface
participations, area `0.0.0.0`, point-to-point network type, and non-passive
state. Cost, authentication, timers, redistribution, summarization, defaults,
BFD, management interfaces, and `access-sw-01` are outside the envelope.

The deterministic O-to-D1 artifacts bind both the managed-O and OSPF-D1
digests. Core and transit render exact IOS interface participation and process
1/router-ID commands without broad network statements. Junos renders its exact
router ID and two area-0 `.0` interface members with `p2p` type. The current O
requires no removal commands; exact wrong-area or passive leaves would be
deleted without replacing the complete OSPF hierarchy.

## Combined Batfish assurance

The active profiled service stack is now, in exact order:

1. `routed_underlay`
2. `ospf`

The routed-underlay D1 remains
`sha256:d25f753ef711677ccdde67bfeb7005f19759800099734a79bca1616bb77baf6b`.
The combined four-node candidate digest is
`sha256:7e7f67500084682194be69d81d94f58d8ae0f6c8722e5de3b3a6c25521e5c269`.

Pinned PyBatfish `2025.7.7.2423` and Batfish server
`2026.07.20.3565` passed all 16 invariants:

- exact four files/nodes, successful parsing, and zero initialization issues;
- exact six routed prefixes, two participants per `/30`, direct flows, and no
  access/management participation;
- exact OSPF routers `core-02`, `edge-junos-01`, and `transit-ios-01` with
  router IDs `.1`, `.2`, and `.3` from the routing-identity pool;
- exact six area-0 point-to-point non-passive interfaces;
- exact adjacency pairs core–Junos, core–transit, and Junos–transit;
- core learns `10.60.0.8/30`, Junos learns `10.60.0.4/30`, and transit learns
  `10.60.0.0/30` through OSPF, including legitimate ECMP where modeled; and
- all three representative remote-link reachability checks pass.

The final-state candidate contains neither legacy `10.6.12.0/30` state nor
transition deletes, management addresses, secrets, or device credentials.

## Safety and compatibility

Network-device writes were zero. CML, OpenBao policies/credentials, host trust,
Terraform, and protected-write authority were unchanged. The B4-2 NetBox
router-ID objects were the only external mutation. Profiled inventory remains
exact devices 1/2/8/9; legacy inventory, Oxidized, observability, SNMP, and
protected writes remain exact devices 1/2. B4-1 standalone assurance remains
10/10 with `ospf_absent`, and all four paused pipeline areas remain disabled.
