# Profile-bound read-only inventory

## Scope and compatibility boundary

Detour B2 makes the B1 profile and management contracts executable only in a
parallel read-only path. `ProfiledInventoryDevice` and
`ProfileReadOnlyAdapter` are not imported by current planning, fleet,
deployment, promotion, Buildkite, Terraform, or staging code. The v1
`InventoryDevice`, its two-value platform field, serialized plans/evidence, and
canonical digests remain unchanged.

[ADR 0024](../adr/0024-two-router-live-and-ephemeral-staging.md) remains current
reference-environment truth. This document does not claim that
`transit-ios-01` or `access-sw-01` exists.

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
| `cisco-ios` | `iosv-159-3-m12` | `iosv_159_3_m12` | `cml_iosv_159_3_m12` | Required by B3; not claimed present |
| `cisco-ios` | `iosvl2-2020` | `iosvl2_2020` | `cml_iosvl2_2020` | Required by B3; not claimed present |
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
| Device | `ncdp-managed` | Device is in the managed population |
| Interface | `ncdp-management-attachment` | The one physical management attachment |
| Interface | `ncdp-protected` | Interface cannot be a managed write target |
| IP address | `ncdp-management-live` | LIVE management endpoint purpose |
| IP address | `ncdp-management-staging` | STAGING management endpoint purpose |

Resolution requires one active managed device, one attachment, one LIVE IP,
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
devices are active, managed, have exact LIVE primary and existing STAGING
secondary relationships, and use protected management interfaces. They are not
B2-profile-ready because role `lab-router` is outside the exact role vocabulary
and the attachment/LIVE/STAGING tags are absent.

| Readiness property | `core-02` current fact | `edge-junos-01` current fact | Required B3 change |
|---|---|---|---|
| Usable factual platform | Yes: `cisco-ios-xe` | Yes: `juniper-junos` | None |
| Usable factual device type | Yes: `c8000v` | Yes: `vjunos-router-lab` | None |
| Usable operational role | No: `lab-router` | No: `lab-router` | Assign exact `core` / `edge` role identity |
| Management attachment tag | Missing | Missing | Tag interface ID 1 / 3 |
| LIVE purpose tag | Missing | Missing | Tag IP ID 1 / 2 |
| STAGING purpose tag | Missing | Missing | Tag IP ID 11 / 12 |
| Exact LIVE primary relationship | Yes | Yes | Preserve |
| Exact STAGING secondary relationship | Yes | Yes | Preserve and explicitly tag |

### Required B3 changes

B3 must separately review and mutate NetBox authority to:

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
| `cat8000v_iosxe` | Ansible `network_cli` + `cisco.ios` collection | libssh |
| `iosv_159_3_m12` | Ansible `network_cli` + `cisco.ios` collection | Paramiko |
| `iosvl2_2020` | Ansible `network_cli` + `cisco.ios` collection | libssh |
| `vjunos_router` | PyEZ/NETCONF | existing hardened Junos transport |

Inspection used installed ansible-core 2.21.3, ansible.netcommon 8.6.0,
ansible-pylibssh 1.4.0, Paramiko 4.0.0, and cisco.ios 11.4.2. The
`network_cli` plugin accepts exact inventory variable
`ansible_network_cli_ssh_type` values `libssh` or `paramiko`; its `auto` mode can
fall back, so B2 never selects `auto`. Run-scoped environment disables both
Paramiko and libssh host-key auto-add, while existing trust is verified before
Runner starts. No libssh host-key/KEX override is set.

The exact IOSv profile selects Paramiko because its library negotiation may
support the proven legacy image without changing system OpenSSH. IOS-XE and
IOSvL2 do not inherit that backend for convenience. The current v1 Cisco path
continues to force Paramiko and is not migrated in B2. Strict-profile and IOSv
real-adapter results are recorded only after bounded read-only acceptance;
missing temporary-node credentials leave that evidence pending rather than
authorizing fallback or global SSH changes.

## Bounded real-adapter result

The B2 acceptance attempt used the already materialized accepted read-only
Oxidized credential source and its private realization-anchored host trust. It
made no configuration request.

| Profile | Target | Backend | Result |
|---|---|---|---|
| `cat8000v_iosxe` | `core-02` | libssh | **STOPPED:** accepted host key does not match the server key presented to libssh |
| `vjunos_router` | `edge-junos-01` | PyEZ/NETCONF | **PASS:** strict trust, hostname `edge-junos-01`, Junos `23.2R1.15`, 42 interfaces |
| `iosv_159_3_m12` | temporary IOSv | Paramiko | **PENDING:** explicit temporary-node credential input is unavailable |
| `iosvl2_2020` | temporary IOSvL2 | libssh | **PENDING:** explicit temporary-node credential input is unavailable |

The follow-up investigation first proved the existing v1 Paramiko control
against the same target, credential, and accepted trust source. It also proved
that the libssh run-scoped `known_hosts` projection was a regular mode-`0600`
file, contained the expected entry, and was byte-for-byte and fingerprint
identical to that accepted source. Private libssh diagnostics then classified
the failure as a server-key mismatch, not a missing trust path and not host-key
or KEX algorithm negotiation. The fact that the accepted entry has key type
`ssh-rsa` does not imply that the server requires legacy SHA-1 signature
negotiation.

**HOST TRUST RE-ENROLLMENT REQUIRED.** B2 does not discover, replace, or delete
the key automatically, add an algorithm override, weaken checking, or fall back
to Paramiko. CAT8000V strict-profile acceptance remains unresolved and
[ADR 0029](../adr/0029-profile-bound-read-only-inventory-and-transport-admission.md)
remains Proposed. IOSv compatibility is likewise not yet accepted: no claim is
made that Paramiko succeeds against exact IOSv M12 until its own credentials are
explicitly supplied.
