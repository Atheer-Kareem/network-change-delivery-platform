# Profile-bound read-only inventory

## Scope and compatibility boundary

Detour B2 makes the B1 profile and management contracts executable only in a
parallel read-only path. `ProfiledInventoryDevice` and
`ProfileReadOnlyAdapter` are not imported by current planning, fleet,
deployment, promotion, Buildkite, Terraform, or staging code. The v1
`InventoryDevice`, its two-value platform field, serialized plans/evidence, and
canonical digests remain unchanged.

[ADR 0031](../adr/0031-four-device-persistent-live-realization.md) now records
current persistent LIVE truth. This document retains the historical B2 audit
and transport admission that preceded external B3 migration.

Detour B3-1 subsequently separates population semantics: the profiled provider
uses only `ncdp-profiled-inventory`, while `ncdp-managed` retains its accepted
legacy exact-two meaning. The exact four-member resolver and realization
contracts are documented in
[profile-aware population and realization](profile-aware-population-and-realization.md).

## Factual profile admission

Profile selection has two explicit stages:

```text
NetBox platform slug -> NetworkOS

exact (platform slug, device-type slug)
    -> AutomationProfileID
    -> CmlRealizationProfileID
```

The closed platform map is:

| NetBox platform slug | Network OS |
|---|---|
| `cisco-ios-xe` | `iosxe` |
| `cisco-ios` | `ios` |
| `juniper-junos` | `junos` |

The closed admission catalog is:

| Platform slug | Device-type slug | Automation profile | CML realization profile | Inventory status |
|---|---|---|---|---|
| `cisco-ios-xe` | `c8000v` | `cat8000v_iosxe` | `cml_cat8000v_17_18_02` | Current fact |
| `cisco-ios` | `iosv-159-3-m12` | `iosv_159_3_m12` | `cml_iosv_159_3_m12` | Current fact |
| `cisco-ios` | `iosvl2-2020` | `iosvl2_2020` | `cml_iosvl2_2020` | Current fact |
| `juniper-junos` | `vjunos-router-lab` | `vjunos_router` | `cml_vjunos_router_23_2r1_15` | Current fact |

Device type is part of NetBox-owned factual identity and distinguishes IOSv
from IOSvL2 while both remain IOS. Git owns the reviewed mapping from those
facts to behavior. Unknown metadata has no fallback. Device name, role, and IP
address do not participate in profile selection.

Role is resolved independently from exact NetBox role slugs `core`, `edge`,
`transit`, and `access`. An absent or different role slug fails closed; behavior
is never inferred from a device name or profile.

## Profiled inventory model

The immutable schema-v1 `ProfiledInventoryDevice` binds:

- stable `netbox:dcim.device:<id>` identity, logical name, and expected hostname;
- full factual NetBox platform, device-type, and role identities;
- independently validated `OperationalRole` and `NetworkOS`;
- exact automation and CML realization profile references;
- the complete B1 `ManagementEndpointSet`; and
- protected stable interface identities and names.

It contains no credentials, configuration, commands, arbitrary provider
options, or CML slot. `InventoryDevice` is not expanded or synthesized for IOSv
or IOSvL2.

## Management metadata and resolution

NetBox remains authoritative for device/interface/IP identity and assignment.
B2 admits these exact tag slugs:

| Object | Tag | Meaning |
|---|---|---|
| Profiled device | `ncdp-profiled-inventory` | Device is eligible for profiled inventory/realization; grants no write or credential authority |
| Interface | `ncdp-management-attachment` | The one physical management attachment |
| Interface | `ncdp-protected` | Interface cannot be a managed write target |
| IP address | `ncdp-management-live` | LIVE management endpoint purpose |
| IP address | `ncdp-management-staging` | STAGING management endpoint purpose |

Resolution requires one active profiled device, one attachment, one LIVE IP,
and one STAGING IP. Both IP objects must be active and assigned to interfaces on
that stable device. Every physical or L3 management interface must be protected.
LIVE exactly equals the device's `primary_ip4` object identity and address;
STAGING is a distinct non-primary identity and numeric address. Both use the
single management service/port admitted by the automation profile. B1's generic
physical/L3 split remains supported.

The installed local NetBox accepts GET filter `interface_id=<positive-id>` on
`/api/ipam/ip-addresses/` and returns only IP objects assigned to that exact
interface. It also accepts `device_id=<positive-id>` for all IPs assigned to
interfaces on one device. The B2 provider uses the device filter, then validates
each returned interface assignment and explicit purpose tag locally. It does
not depend on filtering for a tag that does not exist yet.

Normal B2 code can call only `live_read_only_target()`. There is no purpose
argument, secondary-address fallback, or STAGING projection. B3 must introduce
an explicit staging realization/context whose authority can project STAGING;
that path must never obtain LIVE merely because it is `primary_ip4`.

## Read-only NetBox audit on 2026-08-31

The audit used the accepted local read-only NetBox API credential and issued GET
requests only. Tokens and response headers were not recorded.

### Current facts

| Fact | `core-02` | `edge-junos-01` |
|---|---|---|
| Stable device ID | 1 | 2 |
| Status | Active | Active |
| Tags | `ncdp-fleet-live-001`, `ncdp-managed` | `ncdp-fleet-live-001`, `ncdp-managed` |
| Platform | ID 1, `cisco-ios-xe`, Cisco IOS XE | ID 2, `juniper-junos`, Juniper Junos |
| Device type | ID 1, `c8000v`, C8000V | ID 2, `vjunos-router-lab`, vJunos Router (Synthetic Lab) |
| Role | ID 1, `lab-router`, Lab Router | ID 1, `lab-router`, Lab Router |
| Primary IPv4 | IP ID 1, `192.168.4.14/24` | IP ID 2, `192.168.4.20/24` |
| Management interface | Interface ID 1, `GigabitEthernet1` | Interface ID 3, `fxp0` |
| Management-interface tags | `ncdp-protected` | `ncdp-protected` |
| Other assigned management IP | IP ID 11, `192.168.4.30/24`, Active | IP ID 12, `192.168.4.40/24`, Active |
| IP purpose tags | None on either IP | None on either IP |

Both current platform/device-type pairs are usable factual profile inputs. Both
devices are active in the legacy managed population, have exact LIVE primary
and existing STAGING secondary relationships, and use protected management
interfaces. They are not profile-ready because role `lab-router` is outside the
exact role vocabulary, `ncdp-profiled-inventory` is absent, and the
attachment/LIVE/STAGING tags are absent.

| Readiness property | `core-02` current fact | `edge-junos-01` current fact | Required B3 change |
|---|---|---|---|
| Usable factual platform | Yes: `cisco-ios-xe` | Yes: `juniper-junos` | None |
| Usable factual device type | Yes: `c8000v` | Yes: `vjunos-router-lab` | None |
| Usable operational role | No: `lab-router` | No: `lab-router` | Assign exact `core` / `edge` role identity |
| Profiled population tag | Missing | Missing | Assign `ncdp-profiled-inventory` while preserving `ncdp-managed` |
| Management attachment tag | Missing | Missing | Tag interface ID 1 / 3 |
| LIVE purpose tag | Missing | Missing | Tag IP ID 1 / 2 |
| STAGING purpose tag | Missing | Missing | Tag IP ID 11 / 12 |
| Exact LIVE primary relationship | Yes | Yes | Preserve |
| Exact STAGING secondary relationship | Yes | Yes | Preserve and explicitly tag |

### Required B3 changes

B3 must separately review and mutate NetBox authority to:

- create `ncdp-profiled-inventory` if absent and assign it only to the reviewed
  four-member population; preserve `ncdp-managed` on the legacy exact two;
- create the three closed management metadata tags if absent;
- assign `ncdp-management-attachment` to `core-02` interface ID 1 and
  `edge-junos-01` interface ID 3;
- assign LIVE purpose to IP IDs 1 and 2, and STAGING purpose to IP IDs 11 and
  12, preserving exact primary/non-primary relationships;
- provide exact `core` and `edge` role identity rather than retaining
  `lab-router` or inferring role from names;
- provide platform `cisco-ios` and exact device types `iosv-159-3-m12` and
  `iosvl2-2020` if they do not already exist;
- create the future `transit-ios-01` and `access-sw-01` stable devices,
  interfaces, platform/device-type/role facts, management attachment and
  protected-interface tags, and distinct purpose-tagged LIVE/STAGING IP objects;
  and
- perform authoritative availability/IPAM checks before allocating any new
  management address.

No B0 management proposal such as `.24`, `.25`, `.50`, or `.60` is reserved or
authoritative. B2 creates no `10.60.0.0/16` hierarchy, transit prefix, VLAN,
loopback, or endpoint address. LIVE and STAGING will share identical logical
data-plane addressing as required by B1.

## Read-only adapter and SSH policy

`ProfileReadOnlyAdapter` is an exact facade over shared Cisco and Junos
collection internals. Its only public operations are discovery and bounded
exact-interface collection.

| Automation profile | Provider | Backend |
|---|---|---|
| `cat8000v_iosxe` | Ansible `network_cli` + `cisco.ios` collection | Paramiko |
| `iosv_159_3_m12` | Ansible `network_cli` + `cisco.ios` collection | Paramiko |
| `iosvl2_2020` | Ansible `network_cli` + `cisco.ios` collection | Paramiko |
| `vjunos_router` | PyEZ/NETCONF | existing hardened Junos transport |

The pinned B2 runtime explicitly sets
`ansible_network_cli_ssh_type=paramiko`; it never selects Ansible's `auto` mode
or a fallback. Existing trust is verified before Runner starts, host-key
checking remains enabled, and Paramiko host-key auto-add is disabled. The
catalog and SSH policy contain no KEX or host-key algorithm override. The
current v1 Cisco path continues to force Paramiko and is not migrated in B2.

An earlier B2 design selected libssh for CAT8000V and IOSvL2. CML-anchored
verification proved that `core-02` owns and presents the same accepted RSA key;
no stale key, replacement, or re-enrollment existed. The actual blocker was
that the pinned pylibssh stack did not deterministically consume the required
run-scoped custom trust configuration. B2 therefore standardizes its existing
bounded Ansible Cisco collector on Paramiko and removes pylibssh from the
project dependency set. This is explicit admission, not automatic fallback.

## Bounded real-adapter result

Existing-device acceptance used the already materialized accepted read-only
credential source and its private realization-anchored host trust. Temporary
IOSv and IOSvL2 acceptance used username `netdevops` and explicit isolated
pre-existing operator trust. Every B2 operation was read-only and made no
configuration request.

| Profile | Target | Backend/evidence path | Result |
|---|---|---|---|
| `cat8000v_iosxe` | `core-02` | Ansible/Paramiko control; independent Netmiko/Paramiko | **PASS:** accepted key unchanged; strict trust and read-only collection passed; mismatched/empty trust failed closed |
| `vjunos_router` | `edge-junos-01` | PyEZ/NETCONF | **PASS:** strict trust, hostname `edge-junos-01`, Junos `23.2R1.15`, 42 interfaces |
| `iosv_159_3_m12` | temporary IOSv (`192.168.4.16`) | B2 Ansible/Paramiko collector; independent Netmiko/Paramiko | **PASS:** actual `ProfileReadOnlyAdapter` discovery/collection with strict isolated trust and no algorithm override |
| `iosvl2_2020` | temporary IOSvL2 (`192.168.4.17`) | B2 Ansible/Paramiko collector; independent Netmiko/Paramiko | **PASS:** actual `ProfileReadOnlyAdapter` discovery/collection with strict isolated trust and no algorithm override |

For both temporary Cisco images, the accepted B2 chain was
`ProfileReadOnlyAdapter` to `AnsibleRunnerCiscoAdapter`, the `cisco.ios`
collection, Ansible `network_cli`, and Paramiko. Host-key checking remained
strict, auto-add remained disabled, and no configuration operation or
host-key/KEX relaxation occurred.

The independent feasibility run used Python 3.12.13, Netmiko 4.7.0, and
Paramiko 4.0.0. Netmiko is deliberately not a project dependency: B2 already
has an adequate bounded Cisco collector, and adding another collector would
enlarge the increment without improving its contract. The IOSv and IOSvL2 keys
were copied from already-existing operator trust into isolated temporary files.
That proves bounded transport/image compatibility only; it is not authoritative
B3/NCDP host-trust enrollment and does not make those nodes managed devices.
The later successful B2 Ansible/Paramiko acceptance proves the actual collector
path, but does not change that authority boundary: `.16`, `.17`, their
credentials, and their temporary trust files remain operator-established test
inputs.

No test required `diffie-hellman-group14-sha1`, an `ssh-rsa` compatibility
override, trust mutation, auto-add, or weakened checking. B3 retains authority
for the new devices' NetBox identity, management endpoints, credentials, and
host-trust onboarding.
