# NetBox inventory provider

## Authority boundary

NetBox is the primary personal-lab inventory source for this increment. It owns
the resolved device name and stable object identity, active eligibility,
management endpoint, platform, and interface protection metadata. Git remains
authoritative for change intent, policy, and the desired interface description;
the live device remains observed reality. In particular, the provider does not
read `dcim.interface.description`, and that field is not desired-state authority.

`LocalYamlInventoryProvider` remains available for isolated tests and offline
development. Both implementations satisfy the same `InventoryProvider` boundary;
neither decides workflow policy or contains credentials.

## Fields and eligibility

The provider resolves a device by exact `dcim.device.name` and consumes only:

- device `id`, `name`, `status`, tags, platform slug, and `primary_ip4.address`;
- interface names returned by an explicit device and `ncdp-protected` tag filter.

Exactly one matching device must exist. It must be active, tagged
`ncdp-managed`, use platform slug `cisco-ios-xe`, have a valid primary IPv4, and
have a numeric NetBox object ID. The platform maps to internal `cisco_iosxe`; the
IPv4 prefix is removed and SSH port 22 is fixed for this increment. Protection
results use a bounded limit and fail closed if NetBox reports any next page or a
count that differs from the returned results. Python policy independently
protects `GigabitEthernet1` as well.

## Authentication and transport

`--netbox` reads `NCDP_NETBOX_URL` and `NCDP_NETBOX_TOKEN` from the environment.
The token is sent as `Authorization: Bearer <token>` and never enters CLI
arguments, models, plans, evidence, logs, normalized errors, snapshots, or Runner
artifacts. Use a dedicated enabled NetBox v2 token with `write_enabled = false`,
an appropriate lab expiry, and a source-IP restriction where practical. Normal
provider operation issues GET requests only.

HTTPS certificate verification uses the HTTP client's normal trust validation.
Authenticated redirects are not followed. Requests have explicit bounded
timeouts and query parameters are encoded by the HTTP client. Plain HTTP is
rejected unless the hostname is exactly `localhost`, `127.0.0.1`, or `::1`; a
local NetBox service should bind only to loopback.

## Immutable provenance

Resolved devices carry `inventory_source` and `inventory_object_id`. NetBox uses
`netbox:dcim.device:<id>` rather than a display name; local YAML uses source
`local_yaml` and a null external object identity. Both fields are frozen into the
deployment plan, covered by its digest, and copied into `ChangeRecord` evidence.
Deploy re-resolves inventory and compares provenance, name, endpoint, platform,
and expected hostname before loading device credentials or opening a connection.
Any mismatch returns `STALE_PLAN` with zero device writes.

## Limitations

This increment resolves one exact device name only. It does not implement fleet
selectors, NetBox writes, custom SSH ports, desired configuration in NetBox,
OpenBao, Junos, topology/IPAM policy, or a dynamic provider plugin system. Local
lab bootstrap is an administrative setup activity outside normal NCDP execution.
