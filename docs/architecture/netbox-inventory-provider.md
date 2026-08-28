# NetBox inventory provider

## Authority boundary

NetBox is the primary personal-lab inventory source for this increment. It owns
the resolved device name and stable object identity, requested interface name
and stable object identity, active eligibility, management endpoint, platform,
and interface protection metadata. Git remains
authoritative for change intent, policy, and the desired interface description;
the live device remains observed reality. In particular, the provider does not
read `dcim.interface.description`, and that field is not desired-state authority.

ADR 0024 retains exactly two logical devices. Device 1 (`core-02`) has primary
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
`ncdp-managed`, use platform slug `cisco-ios-xe`, have a valid primary IPv4, and
have a numeric NetBox object ID. Planning additionally requires exactly one
exact-name interface on that resolved device and a numeric interface object ID.
The platform maps to internal `cisco_iosxe`; the IPv4 prefix is removed and SSH
port 22 is fixed for this increment. Protection results use a bounded limit and
fail closed if NetBox reports any next page or a count that differs from the
returned results. Python policy independently protects `GigabitEthernet1` as
well.

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

This increment resolves one exact device name only. It does not implement fleet
selectors, NetBox writes, custom SSH ports, desired configuration in NetBox,
OpenBao, Junos, topology/IPAM policy, or a dynamic provider plugin system. Local
lab bootstrap is an administrative setup activity outside normal NCDP execution.
