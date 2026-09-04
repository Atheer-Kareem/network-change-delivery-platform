# NetBox inventory provider

> **Current boundary:** the profiled provider and exact-four catalog are the
> sole managed-population authority. References below to `InventoryDevice`,
> `NetBoxInventoryProvider`, `ncdp-managed`, schema-v1 plans, or exact-two fleet
> selection describe retained compatibility/history, not current execution.

This document describes the accepted v1 provider used by planning and
deployment. Detour B2 adds a separate
[profile-bound read-only provider](profile-bound-read-only-inventory.md) without
changing this schema, its two-platform mapping, or its runtime consumers.

## Authority boundary

NetBox is the primary personal-lab inventory source. It owns
the resolved device name and stable object identity, requested interface name
and stable object identity, active eligibility, management endpoint, platform,
device type, role, and interface protection metadata. Git remains
authoritative for change intent, policy, and the desired interface description;
the live device remains observed reality. In particular, the provider does not
read `dcim.interface.description`, and that field is not desired-state authority.

The v1 population retains exactly two logical devices. Device 1 (`core-02`) has primary
`.14` and secondary staging `.30` on `GigabitEthernet1`; device 2
(`edge-junos-01`) has primary `.20` and secondary staging `.40` on `fxp0`.
Normal inventory resolution continues to use the primary address. The staging
driver separately verifies the exact secondary `ipam.ipaddress` assignment to
the same management interface before using it.

`LocalYamlInventoryProvider` remains available for isolated tests and offline
development. Both implementations satisfy the same `InventoryProvider` boundary;
neither decides workflow policy or contains credentials.

## Fields and eligibility

The provider resolves a device by exact `dcim.device.name` and consumes only:

- device `id`, `name`, `status`, tags, platform slug, and `primary_ip4.address`;
- requested interface `id` and `name`, filtered by device and exact name;
- interface names returned by an explicit device and `ncdp-protected` tag filter.

Exactly one matching device must exist. It must be active, tagged
`ncdp-managed`, use a supported platform slug, have a valid primary IPv4, and
have a numeric NetBox object ID. The exact platform mappings are
`cisco-ios-xe` to internal `cisco_iosxe` on TCP/22 and `juniper-junos` to
internal `junos` on TCP/830. Planning additionally requires exactly one
exact-name interface on that resolved device and a numeric interface object ID.
The IPv4 prefix is removed. Protection results use a bounded limit and fail
closed if NetBox reports any next page or a count that differs from the returned
results. Python policy independently protects `GigabitEthernet1` as well.

## Authentication and transport

`--netbox` reads `NCDP_NETBOX_URL` and `NCDP_NETBOX_TOKEN` from the environment.
The token is sent as `Authorization: Bearer <token>` and never enters CLI
arguments, models, plans, evidence, logs, normalized errors, snapshots, or Runner
artifacts. Use a dedicated enabled NetBox v2 token with `write_enabled = false`,
an appropriate lab expiry, and a source-IP restriction where practical. Normal
provider operation issues GET requests only.

HTTPS certificate verification uses the HTTP client's normal trust validation.
Authenticated redirects are not followed. Requests have explicit bounded
timeouts, ignore environment proxy routing, and encode query parameters through
the HTTP client. Production proxy support requires an explicit reviewed design.
Plain HTTP is rejected unless the hostname is exactly `localhost`, `127.0.0.1`,
or `::1`; a
local NetBox service should bind only to loopback. Configured URLs must have an
empty or root path; reverse-proxy subpaths are not supported in this increment.

## Personal-lab lifecycle

The accepted local NetBox 4.6.7 authority remains the existing netbox-docker
5.0.2 Compose project named `netbox-docker`. Its upstream services do not define
restart policies, so a user LaunchAgent runs a repository-independent one-shot
reconciler at login and every five minutes. The reconciler waits boundedly for
Docker Desktop, verifies the frozen external Compose inputs, accepted local image
identity, exact service population, existing named volumes, and project
identity, then runs Compose with pull and build disabled. It verifies that only
the NetBox application publishes `127.0.0.1:8000` and exits zero only after the
existing private read-only API token proves the exact two-device managed
population is readable. The token remains external, mode `0600`, and is neither
embedded in the LaunchAgent nor changed by lifecycle installation.

This mechanism owns container availability only. It preserves the existing
PostgreSQL, Redis, media, reports, and scripts volumes and never seeds, migrates,
repairs, or writes NetBox authority. Missing volumes or an unexpected project,
container, image, service, or publication fail closed without automatic
deletion. A completely absent expected container set may be recreated against
those already-verified volumes; a partial or foreign population is rejected.
NCDP inventory semantics and NetBox's authority ownership are unchanged.

## Immutable provenance

Resolved devices carry `inventory_source`, `inventory_object_id`, and
`inventory_interface_object_id`. NetBox uses `netbox:dcim.device:<id>` and
`netbox:dcim.interface:<id>` rather than display names; local YAML uses source
`local_yaml` and null external object identities. All fields are frozen into the
deployment plan, covered by its digest, and copied into `ChangeRecord` evidence.
Deploy re-resolves the target and requested interface and compares both stable
object identities, provenance, name, endpoint, platform, and expected hostname
before loading device credentials or opening a connection. Any mismatch returns
`STALE_PLAN` with zero device writes.

## Limitations

An exact-name operation resolves one device. The same provider also supports the
narrow `ncdp-managed` tag-selected fleet and complete active managed population
used by protected delivery and observability. Platform eligibility remains
limited to the exact Cisco IOS XE and Junos mappings above. The provider does
not implement NetBox writes, custom management ports, desired configuration in
NetBox, credential resolution, general topology/IPAM policy, or a dynamic
provider plugin system. Local lab bootstrap is an administrative setup activity
outside normal NCDP execution.

The parallel B2 provider additionally resolves factual platform/device-type
admission, independent operational role, explicit physical management
attachment, and purpose-tagged LIVE/STAGING IP objects. It preserves the full
endpoint set but exposes only a LIVE read-only target. It is not imported by v1
planning or delivery. B3 has now established exact profile metadata for devices
1, 2, 8, and 9; only the parallel profiled provider can represent the classic
IOS members.

## B3-5 reference data-plane authority

The additive `NetBoxReferenceDataPlaneProvider` resolves the exact reference
allocation separately from v1 inventory. It issues GET requests only and
requires exact `ncdp-data-plane` populations: seven prefixes, two VLANs, six
routed interfaces, and six assigned routed IP objects. The closed Git catalog
checks every accepted NetBox object ID and value, site, VLAN-prefix association,
device/interface identity, cable, and address assignment. It does not infer
authority from a tag, address range, or naming pattern, and it fails closed on
missing, extra, duplicated, wrong, or swapped facts.

The normal application reader has one additional NetBox object permission,
`NCDP data-plane read-only`, with only the `view` action and only
`ipam.prefix` and `ipam.vlan` content types. Existing device, interface, and IP
GET access is preserved. The normal token remains non-write-enabled; it has no
create, update, or delete permission. All B3-5 NetBox writes are confined to
the explicit local administrative migration tool.

These IPAM assignments are authoritative intended relationships. They do not
claim that the routed addresses, VLANs, gateways, OSPF, or ACLs exist in running
device configuration. No primary or management address is changed.
