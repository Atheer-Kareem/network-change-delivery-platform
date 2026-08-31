# Multi-device architecture contract

## Status and compatibility boundary

Detour B1 defines additive architecture contracts for a multi-device
reference environment. Detour B2 connects factual NetBox metadata and exact
automation profiles only through a parallel
[read-only inventory and adapter path](profile-bound-read-only-inventory.md).
Detour B3-4 accepts the four-device persistent LIVE realization, and B3-5
accepts its exact NetBox data-plane/IPAM authority. B4-1 consumes that factual
authority through an additive routed-underlay desired-state vertical without
integrating classic IOS into legacy planning, write adapters, protected
delivery, Terraform, or promotion.

[ADR 0031](../adr/0031-four-device-persistent-live-realization.md) is current
truth for persistent LIVE. ADR 0024 remains historical truth for the legacy
exact-two runtime and the currently disabled two-router Terraform staging
implementation. No four-device STAGING or new deployment authority is claimed.

Current `InventoryDevice`, `DeploymentPlan`, fleet-plan/member,
`ChangeRecord`, `FleetChangeRecord`, `ChangeAuditRecord`,
`ConfigurationObservationRecord`, and promotion schemas remain v1. Their
serialized fields and canonical digest inputs are unchanged. The B1 types and
B2 profiled inventory live outside current execution paths. B2 does not expand
the v1 platform field or synthesize legacy `InventoryDevice` values for IOSv or
IOSvL2.

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

Strict pre-existing host-key verification is mandatory for every profile. The
policy cannot express global or profile-local host-key/KEX algorithm
relaxation. B1 changed no Ansible, Paramiko, OpenSSH, known-host, or Junos
transport behavior.

The current v1 Cisco implementation explicitly sets
`ansible_network_cli_ssh_type=paramiko`. Documentation describing that current
path as libssh was incorrect; B1 corrects the documentation without changing
the implementation. B2's separate read-only catalog explicitly selects
Paramiko for all three Cisco profiles. It never selects Ansible's automatic
backend fallback. Strict host trust and disabled auto-add remain mandatory; no
KEX or host-key algorithm is relaxed. Bounded feasibility against the exact
IOSv and IOSvL2 images passed without overrides. The earlier OpenSSH-based IOSv
compatibility hypothesis is therefore not retained as transport authority.

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
identities may be equal, but need not be. A platform may therefore use one
physical interface as both attachment and routed L3 owner, or terminate a
physical management attachment on a distinct logical interface.

Accepted evidence for the exact IOSvL2 2020 image proves that
`Gi0/0` supports `no switchport`, a routed management address, up/up state,
management reachability, and SSH. The `access-sw-01` binding uses `Gi0/0` for
both physical attachment and L3 management ownership.
`Vlan1` is not part of that preferred realization.

A generic management binding contains no CML slot. Slot mapping is realization
data, not stable inventory or IPAM identity.

## Management endpoint purpose and resolution

`ManagementEndpointPurpose` is closed to `LIVE` and `STAGING`. Purpose is
semantic identity; it is never inferred from an address, subnet, numeric range,
or primary/secondary label.

A `ManagementEndpointSet` binds one stable logical device and automation profile
to exactly one endpoint of each purpose. Both bindings must use the same stable
physical and L3 interface identities. Their NetBox IP-address object identities
and numeric addresses must differ, and each service/port must be admitted by the
automation profile. This generic structure contains no CML slot.

Future normal NCDP inventory and deployment resolution may select only the LIVE
endpoint. Disposable staging may select only the STAGING endpoint, and only
through an explicit admitted staging realization/context. A staging path must
never receive the LIVE endpoint merely because NetBox exposes it as
`primary_ip4`.

NetBox remains authoritative for both IP objects and their interface assignment.
The LIVE endpoint remains the device's exact NetBox primary IPv4. The STAGING
endpoint is an explicitly admitted alternate/staging address. B2 freezes
IP-address tags `ncdp-management-live` and `ncdp-management-staging`, plus
physical-interface tag `ncdp-management-attachment`, as the closed semantic
metadata. B3-2 created and assigned those exact tags; B3-4 accepted their LIVE
resolution.

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

The IOSvL2 realization uses bootstrap profile
`iosvl2_routed_management`: slot 0 maps to routed `Gi0/0` for management.
Readiness profile `iosvl2_routed_ssh` requires SSH on that routed interface.
Neither profile uses a management SVI. The IOSvL2 automation profile retains
the separate `svi` capability for future managed data-plane use.

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
| NetBox | Stable device/interface identity, platform/NOS and device-type metadata, role, physical topology/cabling, management/IPAM relationships, VLAN object identity, VID, canonical VLAN name, prefix/IP identity |
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

Detour B3-5 establishes this exact NetBox-owned allocation hierarchy:

```text
10.60.0.0/16  NCDP data-plane parent
├── 10.60.0.0/30   core-02 ↔ edge-junos-01
├── 10.60.0.4/30   core-02 ↔ transit-ios-01
├── 10.60.0.8/30   edge-junos-01 ↔ transit-ios-01
├── 10.60.10.0/24  VLAN 10 USERS
├── 10.60.20.0/24  VLAN 20 SERVERS
└── 10.60.255.0/24 future loopback/router-ID allocation pool
```

The three routed links have exact NetBox-owned interface assignments:
`10.60.0.1/30` on `core-02/GigabitEthernet4`, `10.60.0.2/30` on
`edge-junos-01/ge-0/0/0`, `10.60.0.5/30` on
`core-02/GigabitEthernet2`, `10.60.0.6/30` on
`transit-ios-01/GigabitEthernet0/1`, `10.60.0.9/30` on
`edge-junos-01/ge-0/0/1`, and `10.60.0.10/30` on
`transit-ios-01/GigabitEthernet0/2`.

`NetBoxReferenceDataPlaneProvider.resolve_reference_allocation()` resolves only
this exact tagged population through GET requests and validates the accepted
NetBox identities, values, interface ownership, cables, and VLAN-prefix
relationships against the closed Git-owned topology catalog. Missing, extra,
duplicated, wrong, or swapped facts fail closed. The copied IDs and values in
the catalog are admission evidence, not a second source of IPAM authority.

No individual loopback/router-ID, VLAN gateway, or endpoint address is allocated
yet. No routed address or VLAN has been configured on a device. Git will own
only how these resolved objects participate in later VLAN, OSPF, ACL, and
assurance intent.

## Logical network and realization identity

LIVE and STAGING are two realizations of the same logical network. They use
identical logical data-plane intent and resolved values for:

- routed link prefixes and data-plane interface addresses;
- loopback/router-ID addresses;
- VLAN IDs and prefixes;
- gateway and endpoint addresses;
- OSPF intent; and
- ACL/security intent.

Only externally reachable management endpoints differ. This invariant makes
disposable staging a digital twin rather than a separately addressed logical
network.

Managed logical device names remain `core-02`, `edge-junos-01`,
`transit-ios-01`, and `access-sw-01` in both realizations. Staging must not
rename them with suffixes such as `core-02-staging`. The containing realization
distinguishes `NCDP Live / core-02` from
`NCDP Staging <run-id> / core-02`: logical identity is shared while run/lab/node
realization identity differs. B3-2 and B3-4 now establish these stable LIVE
device identities. A future STAGING realization must retain the same logical
names.

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

Scope identity namespaces are closed and kind-specific:

- device: `netbox:dcim.device:<positive-id>`;
- interface: `netbox:dcim.interface:<positive-id>`;
- VLAN: `netbox:ipam.vlan:<positive-id>`;
- prefix: `netbox:ipam.prefix:<positive-id>`; and
- Git-owned policy: `git:policy:<safe-stable-token>`.

The policy token uses lowercase alphanumeric segments separated only by `.`,
`_`, or `-`. A kind cannot carry another kind's namespace or arbitrary text.

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

## Reference topology and deferred services

### Current physical realization

The operator-owned `NCDP Live` CML lab contains these accepted physical links:

- `core-02 GigabitEthernet4` to `edge-junos-01 ge-0/0/0`;
- `core-02 GigabitEthernet2` to `transit-ios-01 GigabitEthernet0/1`;
- `edge-junos-01 ge-0/0/1` to `transit-ios-01 GigabitEthernet0/2`; and
- `core-02 GigabitEthernet3` to `access-sw-01 GigabitEthernet0/1`.

`transit-ios-01 GigabitEthernet0/0` is its physical and routed L3 management
interface. `access-sw-01 GigabitEthernet0/0` is likewise its dedicated physical
and routed L3 management interface. These management paths are independent of
future data-plane service configuration.

`transit-ios-01 GigabitEthernet0/3` and `edge-junos-01 ge-0/0/2` remain spare.
`access-sw-01 GigabitEthernet0/2` and `GigabitEthernet0/3` remain physically
available for the future USERS and SERVERS endpoint fixtures.

### Current management authority

NetBox owns these exact management endpoints:

| Device | LIVE | STAGING allocation |
|---|---|---|
| `core-02` | `192.168.4.14/24` | `192.168.4.30/24` |
| `edge-junos-01` | `192.168.4.20/24` | `192.168.4.40/24` |
| `transit-ios-01` | `192.168.4.16/24` | `192.168.4.31/24` |
| `access-sw-01` | `192.168.4.17/24` | `192.168.4.32/24` |

The LIVE endpoints are realized and admitted. The STAGING IP objects are
allocated in NetBox, but no four-device STAGING realization is claimed or
active; that realization remains deferred until explicit operator decision.

### Current B3-5 data-plane authority

NetBox owns the exact allocation hierarchy established by B3-5:

- `10.60.0.0/16`: NCDP data-plane parent;
- `10.60.0.0/30`: core/Junos routed link;
- `10.60.0.4/30`: core/transit routed link;
- `10.60.0.8/30`: Junos/transit routed link;
- `10.60.10.0/24`: VLAN 10 `USERS`;
- `10.60.20.0/24`: VLAN 20 `SERVERS`; and
- `10.60.255.0/24`: future router-ID/loopback allocation pool.

The routed interface IP assignments are authoritative NetBox/IPAM
relationships, not claims about current device running configuration.

### Current B4-1 routed-underlay proposal

Git now owns one narrow `routed_underlay` managed ownership envelope over the
three routed prefixes and six stable data-plane interface identities above. Its
normalized fields are only routed L3 presence, the interface address/prefix,
and admin-enabled state. It does not own descriptions, operational status,
management interfaces, OSPF, VLANs, ACLs, or unrelated configuration.

`RoutedUnderlayIntent.from_reference_allocation()` accepts only the exact
`ReferenceDataPlaneAllocation`; each link and endpoint in the intent must equal
the frozen resolved NetBox copy. `RoutedUnderlayDesiredState` then normalizes
the six interfaces independently of vendor configuration text and binds them to
a deterministic digest. This proposed state is D1 only. It is not D0 and is not
an `AcceptedManagedStateRef`.

The read-only observation path resolves the exact profiled LIVE population,
loads credentials by stable NetBox device identity, projects only each LIVE
target, and calls `ProfileReadOnlyAdapter.collect()` for the exact six
interfaces. Cisco IOS XE/IOS and Junos change renderers consume both current O
and proposed D1. They produce exact managed-address removals/additions and
admin-enable intent without replacing broader interface subtrees. A separate
D1-only renderer produces the final-state Batfish candidate. B4-1 adds no
execution method and grants no write authority.

The offline candidate contains all four profiled nodes but only core, Junos,
and transit participate in the routed underlay. Batfish verifies exact parse
and node populations, the six interface prefixes, two participants per `/30`,
three direct-neighbor flows, access-switch exclusion, management-address
exclusion, and absence of OSPF. The candidate did not require a separate
layer-1 file for directly connected reachability; its interface/prefix facts
remain derived from the exact accepted physical and NetBox link relationships.
See the [B4-1 acceptance record](../acceptance/routed-underlay-detour-b4-1.md).

### Still future and not configured

The physical realization and NetBox allocations do not configure services.
These items remain future reviewed increments:

- applying the B4-1 routed-underlay proposal to devices;
- creating VLANs on devices;
- creating IOS-XE router-on-a-stick subinterfaces on `core-02`;
- configuring the `core-02` to `access-sw-01` trunk;
- configuring VLAN 10 and VLAN 20 access ports;
- allocating and configuring VLAN gateways;
- configuring OSPF;
- configuring ACLs or security policy;
- creating endpoint nodes or allocating endpoint addresses; and
- allocating individual loopback/router-ID addresses.

The initial service design keeps `access-sw-01` as the managed access-switching
boundary: `GigabitEthernet0/1` will be the 802.1Q trunk,
`GigabitEthernet0/2` the VLAN 10 USERS access port, and
`GigabitEthernet0/3` the VLAN 20 SERVERS access port. `core-02` will initially
own inter-VLAN routing through IOS-XE 802.1Q subinterfaces. This does not make
`access-sw-01` a VLAN gateway or claim broader IOSvL2 routing behavior. A later
gateway migration to switch SVIs remains a distinct coordinated service change.

The reserved future traffic fixtures remain `users-host-01` and
`servers-host-01`, likely implemented as lightweight Alpine CML nodes. They are
not NCDP-managed network devices, fleet members, canaries/waves,
network-device `DeploymentPlan` recipients, credential owners, or members of
the four-device managed-network population. Their eventual data-plane addresses
must remain identical between LIVE and STAGING realizations.
