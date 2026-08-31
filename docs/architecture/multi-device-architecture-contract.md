# Multi-device architecture contract

## Status and compatibility boundary

Detour B1 defines additive architecture contracts for a future multi-device
reference environment. It does not integrate those contracts into current
inventory resolution, planning, rendering, adapters, protected delivery,
Terraform, CML, observability, or promotion.

[ADR 0024](../adr/0024-two-router-live-and-ephemeral-staging.md) remains the
current truth: the managed live and disposable reference environments contain
only `core-02` and `edge-junos-01`. The future device and address material below
is provisional and creates no inventory, allocation, credential, realization,
or deployment authority.

Current `InventoryDevice`, `DeploymentPlan`, fleet-plan/member,
`ChangeRecord`, `FleetChangeRecord`, `ChangeAuditRecord`,
`ConfigurationObservationRecord`, and promotion schemas remain v1. Their
serialized fields and canonical digest inputs are unchanged. The B1 types live
in a separate module and are not imported by current execution paths. B2 must
make any integration an explicit versioned migration rather than silently
expanding a v1 platform field.

## Independent identity dimensions

The architecture enforces this separation:

```text
NetworkOS
!= operational role
!= capability set
!= automation profile
!= CML realization profile
```

`NetworkOS` is a closed vocabulary: `iosxe`, `ios`, and `junos`. IOSv and
IOSvL2 both run IOS. They are not represented as fabricated network operating
systems such as `ios_switch` or `iosvl2`.

Operational role is separate and initially closed to `core`, `edge`, `transit`,
and `access`. NetBox ultimately owns each device's role identity. Role does not
select vendor behavior or imply capability.

Capabilities are selected only by the reviewed Git-owned profile catalog. The
initial vocabulary is `layer3_routing`, `layer2_switching`, `svi`,
`dot1q_trunk`, `access_port`, `ospf`, `ios_acl`, `junos_firewall_filter`, and
`commit_confirmed`. No capability is inferred merely from a vendor or NOS name.

## Automation profiles

An automation profile is a closed behavioral selection containing NOS,
admitted capabilities, transport, adapter, renderer, collector, readiness,
recovery, and profile-local SSH policy. It is not a generic plugin mechanism.

| Profile | NOS | Principal admitted behavior |
|---|---|---|
| `cat8000v_iosxe` | `iosxe` | Layer-3 routing, 802.1Q, OSPF, IOS ACL |
| `iosv_159_3_m12` | `ios` | Layer-3 routing, OSPF, IOS ACL |
| `iosvl2_2020` | `ios` | Layer-2 switching, SVI, trunk and access port |
| `vjunos_router` | `junos` | Layer-3 routing, OSPF, Junos firewall filter, commit-confirmed |

The IOSvL2 profile deliberately does not yet admit unproven PACL/VACL behavior.
Catalog membership is architectural data in B1 and has no effect on current
provider dispatch.

## SSH compatibility policy

Legacy SSH compatibility is representable only inside the exact
`iosv_159_3_m12` profile. The catalog records that B2 real-adapter acceptance
may require `diffie-hellman-group14-sha1` key exchange and an `ssh-rsa` host key.
That possibility is not an accepted transport relaxation.

The policy cannot express a global legacy setting. Strict host-key verification
is mandatory for every profile. IOS-XE and Junos profiles do not inherit the
IOSv possibility. B1 changes no Ansible, Paramiko, libssh, OpenSSH, known-host,
or Junos transport behavior.

The current Cisco implementation explicitly sets
`ansible_network_cli_ssh_type=paramiko`. Documentation describing that current
path as libssh was incorrect; B1 corrects the documentation without changing
the implementation. B2 must validate the exact IOSv image through the real
adapter before selecting any profile-local compatibility behavior.

## Management binding

`ManagementBinding` separates the physical management attachment from the
logical L3 management endpoint:

```text
ManagementBinding
├── physical_attachment
│   └── stable device/interface identity and interface name
└── l3_endpoint
    ├── stable device/interface identity and interface name
    ├── stable IP-address identity and address
    ├── management service
    └── port
```

Both interfaces must belong to the same stable device. Their interface
identities may be equal, but need not be. The IOSvL2 example is a physical CML
cable attached to `Gi0/0` while the management IPv4 address belongs to `Vlan1`.

A generic management binding contains no CML slot. Slot mapping is realization
data, not stable inventory or IPAM identity.

## CML realization profiles

`CmlRealizationProfile` separately represents node definition, exact image
definition, resource policy, physical interface-to-slot mapping, minimal
bootstrap profile, and readiness profile.

| Realization profile | Node definition | Exact image definition | Interfaces by CML slot |
|---|---|---|---|
| `cml_cat8000v_17_18_02` | `cat8000v` | `cat8000v-17-18-02` | 0 `GigabitEthernet1`, 1 `GigabitEthernet2`, 2 `GigabitEthernet3`, 3 `GigabitEthernet4` |
| `cml_iosv_159_3_m12` | `iosv` | `iosv-159-3-m12` | 0 `Gi0/0`, 1 `Gi0/1`, 2 `Gi0/2`, 3 `Gi0/3` |
| `cml_iosvl2_2020` | `iosvl2` | `iosvl2-2020` | 0 `Gi0/0`, 1 `Gi0/1`, 2 `Gi0/2`, 3 `Gi0/3` |
| `cml_vjunos_router_23_2r1_15` | `vjunos-router` | `vjunos-router-23-2r1-15` | 0 `fxp0`, 1 `ge-0/0/0`, 2 `ge-0/0/1`, 3 `ge-0/0/2` |

The catalog preserves the current explicit CAT8000V and vJunos CPU/RAM values.
IOSv and IOSvL2 retain node-definition defaults because B1 does not invent or
optimize unrecorded per-node allocations. The measured aggregate capacity is
the acceptance basis for the initial scope.

This catalog is not consumed by Terraform in B1 and does not create, adopt,
change, or destroy a CML realization.

## Authority

Every managed property has one authority:

| Authority | Properties |
|---|---|
| NetBox | Stable device/interface identity, platform/NOS metadata, role, physical topology/cabling, management/IPAM relationships, VLAN object identity, VID, canonical VLAN name, prefix/IP identity |
| Git | Managed device-configuration intent, VLAN deployment and attachment behavior, access/trunk/native/allowed behavior, gateway/subinterface deployment, OSPF desired behavior, ACL/security flow policy, assurance policy, profile behavior catalog |
| OpenBao | Credentials keyed to stable device identity |
| Device | Observed reality only |
| Terraform/CML state | Exact disposable realization identity and lifecycle only |

A frozen plan may carry a resolved copy of a NetBox-owned value to bind identity,
approval, and execution. The copy is evidence and a stale-input gate; it does
not become a second authority.

For VLANs, NetBox owns object identity, VID, canonical name, and prefix/IP
identity. Git owns whether and how that object is deployed on stable interfaces
and the desired gateway, routing, security, and assurance behavior. The same
desired property must not be independently authored in both systems.

## Managed ownership envelopes

A `ManagedOwnershipEnvelope` defines one vertical, version, exact stable target
and scope identities, and exact normalized fields NCDP owns. It is not a full
running configuration.

Initial examples are:

- VLAN: VLAN presence, port mode, access VLAN, allowed/native set, and owned
  gateway deployment.
- OSPF: process, router ID, interface participation, area, network type, passive
  state, cost, and only explicitly managed authentication/timers.
- ACL: normalized rule semantics and order, attachment, direction, and default
  action.

Unrelated configuration remains outside the envelope. Whole-running-config byte
equality is explicitly prohibited as the managed-drift model.

## Accepted desired-state references

`AcceptedManagedStateRef` is the versioned D0 contract for one ownership
envelope. It binds:

- envelope type, schema/version, exact targets, scope, and normalized fields;
- normalized accepted desired-state digest;
- exact source Git commit; and
- durable acceptance-evidence identity and digest.

D0 is not current `main`, the latest Git commit, the latest Buildkite build, or
the whole running configuration. Different verticals can have independently
accepted baselines:

```text
D0_vlan != D0_ospf != D0_acl
```

B1 defines no persistence or resolution mechanism. B5 will persist and resolve
these references and compare normalized observed state.

The lifecycle contract is:

```text
Pull request:       D0 -> D1
Protected prewrite: fresh relevant O compared with D0
Drift:              DRIFT_DETECTED -> zero writes -> fail closed
Post-write:         fresh relevant O' compared with D1
```

Out-of-band managed drift is never silently overwritten, automatically healed,
or accepted because a device is reachable. An operator either restores reviewed
desired state through normal delivery or adopts legitimate emergency reality
into reviewed Git intent.

## Future coordinated service delivery

Ordinary fleet rollout is sufficient only when every rollout prefix is
independently safe. Some VLAN, OSPF, and ACL changes require ordered service
sequencing. The smallest likely future abstraction is a
`CoordinatedServicePlan` with the bounded phase vocabulary:

```text
prepare
-> attach/activate
-> enable routing/enforcement
-> service validation
-> optional cleanup
```

B1 does not define or execute such a plan and does not create an arbitrary DAG
engine. Pre-write drift or ambiguity gives zero writes. Ambiguity after
execution has begun has different semantics: stop immediately, do not retry, do
not expose later phases or members, preserve the partial outcome, and reconcile
independently. It must never be described as necessarily producing zero writes.

## Provisional future reference topology

The following is a future proposal, not current runtime truth:

```text
core-02 <-------> edge-junos-01
   \                  /
    \                /
     transit-ios-01

core-02
   |
802.1Q trunk
   |
access-sw-01
   |        |
VLAN 10  VLAN 20
USERS    SERVERS
```

The accepted current core-to-Junos link is preserved as
`core-02 GigabitEthernet4` to `edge-junos-01 ge-0/0/0`. Proposed additions are:

- `core-02 GigabitEthernet2` to `transit-ios-01 Gi0/1`;
- `edge-junos-01 ge-0/0/1` to `transit-ios-01 Gi0/2`;
- `core-02 GigabitEthernet3` to `access-sw-01 Gi0/1` as the VLAN 10/20 trunk;
- `access-sw-01 Gi0/2` as the USERS access attachment;
- `access-sw-01 Gi0/3` as the SERVERS access attachment;
- `transit-ios-01 Gi0/0` as physical and logical management; and
- `access-sw-01 Gi0/0` as physical management attachment with `Vlan1` as the
  logical L3 management owner.

`transit-ios-01 Gi0/3` and `edge-junos-01 ge-0/0/2` remain spare. Endpoint-side
interfaces depend on a future endpoint node selection.

Proposed live management addresses `192.168.4.24/24` and
`192.168.4.25/24`, and proposed staging addresses `192.168.4.50/24` and
`192.168.4.60/24`, are synthetic planning values. They are not claimed to be
available, allocated, or present in NetBox. B1 creates none of the proposed
device identities or relationships.
