# Detour B4-1 routed-underlay acceptance

## Scope and authority

B4-1 prepares and assures a proposed routed-underlay change. It does not apply
that proposal to LIVE devices.

The source was the exact GET-only B3-5 `ReferenceDataPlaneAllocation`, resolved
from NetBox with digest
`sha256:1352521feec8f787eb1a468c586dd3390428289314c3984416ab987a8af61b3d`.
Git owns only the three link relationships and proposed admin-up participation.
NetBox remains authoritative for each prefix, stable interface, IP-address
identity/value, and interface assignment.

The `routed_underlay` ownership envelope covers devices 1, 2, and 8, the three
routed prefix identities, and six stable interface identities. Its fields are
only:

- routed L3 presence;
- interface L3 address/prefix; and
- admin-enabled state.

Management, descriptions, operational state, OSPF, loopbacks, VLANs, trunks,
access ports, gateways, ACLs, and `access-sw-01` are not owned by this envelope.
No `AcceptedManagedStateRef` was created; B4-1 D1 is proposed state, not D0.

## Real read-only observed state O

At `2026-08-31T11:05:09.599225+00:00`, the existing exact-four profiled trust,
stable-ID OpenBao credential paths, LIVE-only targets, and
`ProfileReadOnlyAdapter` returned:

| Device/interface | Observed IPv4 | Admin | Operational |
|---|---|---|---|
| `core-02/GigabitEthernet4` | `10.6.12.1/30` | enabled | unreported by normalized Cisco collection |
| `core-02/GigabitEthernet2` | none | disabled | unreported by normalized Cisco collection |
| `edge-junos-01/ge-0/0/0` | `10.6.12.2/30` | enabled | up |
| `edge-junos-01/ge-0/0/1` | none | enabled | up |
| `transit-ios-01/GigabitEthernet0/1` | none | disabled | unreported by normalized Cisco collection |
| `transit-ios-01/GigabitEthernet0/2` | none | disabled | unreported by normalized Cisco collection |

The pre-existing `10.6.12.0/30` core/Junos configuration is therefore a real
managed-envelope delta. B4-1 neither ignored nor changed it.

The earlier admin-token observation was superseded by this final run. The
existing accepted operator mechanism issued one fresh bounded personal-lab
AppRole SecretID, and the committed verifier used its normal
`OpenBaoSecretProvider` path to read only the exact stable-ID credential paths
for devices 1, 2, and 8. Credentials remained memory-only and were not printed
or persisted. The temporary SecretID was destroyed immediately after the run;
the AppRole policy, TTL, use limits, credential paths, and stored device
credentials were unchanged.

## Proposed D1, O-to-D1 change renderings, and final-state candidate

The vendor-independent D1 digest is:

`sha256:d25f753ef711677ccdde67bfeb7005f19759800099734a79bca1616bb77baf6b`

It binds the exact six stable interface/IP identities, one desired `/30`
address per interface, routed L3 presence, and admin enabled. It does not hash
vendor configuration text.

Vendor change artifacts are derived from both observed O and normalized D1.
They remove only addresses inside the routed-underlay ownership envelope before
adding the desired address. Each target also binds the normalized managed-O
digest and the proposed D1 digest, so evidence cannot reuse a render after its
managed observation changes:

| Target/profile | O-to-D1 managed changes | Artifact |
|---|---|---|
| `core-02` / `cat8000v_iosxe` | `GigabitEthernet4`: remove `10.6.12.1/30`, add `10.60.0.1/30`; `GigabitEthernet2`: add `10.60.0.5/30`; `no shutdown` | deterministic IOS CLI |
| `edge-junos-01` / `vjunos_router` | `ge-0/0/0.0`: exact XML delete of `10.6.12.2/30`, add `10.60.0.2/30`; `ge-0/0/1.0`: add `10.60.0.9/30`; remove `disable` | deterministic Junos XML |
| `transit-ios-01` / `iosv_159_3_m12` | `GigabitEthernet0/1` `10.60.0.6/30`; `GigabitEthernet0/2` `10.60.0.10/30`; `no shutdown` | deterministic IOS CLI |

`access-sw-01` has no rendered routed-underlay target.
The Cisco change renderer fails closed if a managed interface has more than one
observed IPv4 address; B4-1 does not guess primary/secondary semantics.

The Batfish configuration is a separate final-state candidate generated only
from D1. It contains no `10.6.12.0/30` address or change command and therefore
analyzes the intended converged topology rather than the transition artifact.

## Batfish candidate assurance

The pinned offline candidate snapshot digest is:

`sha256:d3f545c5df160c29b82974f9d58f6ec76cbcc52037b69f63051e97a4aeed21f0`

PyBatfish `2025.7.7.2423` and Batfish server `2026.07.20.3565` reported:

- exact files `access-sw-01.cfg`, `core-02.cfg`, `edge-junos-01.cfg`, and
  `transit-ios-01.cfg`: all `PASSED`;
- exact four nodes recognized;
- initialization issues: zero;
- exact six intended interface prefixes and exactly two participants per `/30`;
- core `10.60.0.1` to Junos `10.60.0.2`: reachable;
- core `10.60.0.5` to transit `10.60.0.6`: reachable;
- Junos `10.60.0.9` to transit `10.60.0.10`: reachable;
- `access-sw-01` routed participation: none;
- management addresses in the managed candidate envelope: none; and
- OSPF process count: zero.

All ten typed invariants passed. A separate layer-1 topology file was not
required for these directly connected flows; the candidate interface/prefix
relationships came from the exact accepted physical/IPAM allocation.

## Safety and unchanged compatibility

Device configuration writes were zero. NetBox, CML, host trust, stored OpenBao
credentials/policies, Terraform, Buildkite, and pipeline authority were not
mutated. The one bounded acceptance SecretID was issued and then destroyed.
Legacy `ncdp-managed`, Oxidized, observability, SNMP, and protected-write
populations remain exact devices 1/2; profiled inventory remains exact devices
1/2/8/9. The four disabled pipeline runtime blocks remain disabled. Existing
v1 schemas and representative canonical digests remain unchanged.
