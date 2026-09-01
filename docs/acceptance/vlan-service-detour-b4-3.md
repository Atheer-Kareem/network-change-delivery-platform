# Detour B4-3 VLAN service acceptance

## Outcome

Detour B4-3 establishes the proposed VLAN 10/20 router-on-a-stick service from
exact NetBox facts through read-only LIVE observation, normalized D1,
observation-bound rendering, and pinned Batfish assurance. Device writes are
zero. This record is proposal evidence, not D0 and not permission to apply the
change.

## NetBox authority

The no-delete transactional migration completed once and its second run
reported `created=0`, `updated=0`. Exact accepted identities are:

| Object | Stable identity |
|---|---:|
| `ncdp-vlan-gateway` tag | 11 |
| `core-02/GigabitEthernet3` parent | interface 7 |
| `core-02/GigabitEthernet3.10` | interface 21 |
| `core-02/GigabitEthernet3.20` | interface 22 |
| `10.60.10.1/24` gateway | IP address 26 |
| `10.60.20.1/24` gateway | IP address 27 |
| `access-sw-01/GigabitEthernet0/1` | interface 18 |
| `access-sw-01/GigabitEthernet0/2` | interface 19 |
| `access-sw-01/GigabitEthernet0/3` | interface 20 |

Cable 4 remains the exact core parent-to-access trunk relationship. Access
interfaces 19/20 remain uncabled in NetBox and LIVE CML. The accepted factual
allocation digest is
`sha256:3068c48d95639a5f46cffefd53b0f778399b06a58b1a0704cd02e2a9dd338a1b`.
Gateway interfaces/IPs are not tagged `ncdp-data-plane`; the B3-5 exact-six
routed-IP population and B4-2 exact-three routing-identity population remain
unchanged.

## Real managed observation

The final read-only run used `OpenBaoSecretProvider`, exact stable NetBox
credential identities, the exact-four profiled LIVE trust generation, and the
profile-bound Cisco collectors. Its bounded O was:

- core `GigabitEthernet3`: administratively disabled and unaddressed;
- core `GigabitEthernet3.10` and `.20`: absent;
- access VLAN 10 and VLAN 20: absent; and
- access `GigabitEthernet0/1`–`0/3`: enabled, dynamic-auto, VLAN 1.

The managed-O digest is
`sha256:04c4183c7d71e2e14e873f4c59bc8b11ea2022aaf302b04f2d5495ca56f4eb63`.
The bounded AppRole acceptance material was retired after collection.

## Proposed D1 and transition

The normalized VLAN D1 digest is
`sha256:57fe2decfcf6ecaf595a877fac9d2fa4befa0286ec7a70b8235fd514ca3995b3`.
The O-to-D1 artifacts propose only:

- enabling unaddressed core `GigabitEthernet3`;
- creating `.10`/`.20` with exact dot1q tags and gateway addresses;
- creating VLAN 10 `USERS` and VLAN 20 `SERVERS` on the access switch;
- making access `Gi0/1` a trunk allowing exactly 10/20; and
- making `Gi0/2` access VLAN 10 and `Gi0/3` access VLAN 20.

They do not configure a native VLAN, access-switch SVI, OSPF, ACL, or unrelated
interface state. The rendered targets are proposal artifacts only.

## Batfish assurance boundary

The first behavioral attempt originated traffic at the L2-only
`@enter(access-sw-01[Gi0/2|Gi0/3])` locations. Pinned Batfish returned
`NO_ROUTE`: without an L3 endpoint model, the switch cannot originate the host
traffic. This was a modeling-boundary discovery, not a candidate VLAN failure.

The accepted model therefore contains:

- four managed network nodes: `access-sw-01`, `core-02`, `edge-junos-01`, and
  `transit-ios-01`;
- two Batfish-only fixtures: `assurance-users-probe` at synthetic
  `10.60.10.100/24` via `10.60.10.1`, and `assurance-servers-probe` at synthetic
  `10.60.20.100/24` via `10.60.20.1`; and
- six modeled layer-1 edges: the four accepted infrastructure edges plus two
  synthetic host attachments to access `Gi0/2` and `Gi0/3`.

The fixtures are not NetBox allocations/devices, profiled inventory, CML nodes,
credential owners, delivery targets, or ownership-envelope members. No LIVE
endpoint cable or address is claimed.

Pinned PyBatfish `2025.7.7.2423` and Batfish server `2026.07.20.3565` passed all
29 combined invariants. Both host-to-gateway flows and both directions of the
open pre-ACL inter-VLAN baseline passed. Normalized traces include `core-02`
and exclude `edge-junos-01`/`transit-ios-01` as inter-VLAN transit. Remote
routers learn neither service prefix through OSPF.

The deterministic seven-file snapshot digest is
`sha256:18ba3232b8ec85019b0afcfd7239eb3818e8dc788948482a54ffb2eb430dcda6`.
The accepted routed-underlay and OSPF D1 digests remain unchanged.

## Preserved boundaries

No network device, CML realization, OpenBao credential/policy, host trust,
Terraform topology/state, protected authority, or legacy v1 behavior was
changed. Disposable CML staging, protected delivery, observability runtime
validation, and synthetic SNMPv3 runtime validation remain disabled pending
explicit operator decisions.
