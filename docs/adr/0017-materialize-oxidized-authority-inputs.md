# ADR 0017: Materialize Oxidized authority inputs outside the collector

## Status

Accepted for Increment 10C-3.

## Context

Oxidized needs node endpoints, platform models, and credentials, but it is not
inventory or credential authority. Direct collector access to NetBox and
OpenBao would duplicate authority adapters and enlarge the persistent runtime's
trust boundary. The source must also remain private because it contains device
credentials.

## Decision

An NCDP host-side materializer reads NetBox through the existing hardened
GET-only adapter and OpenBao through the existing AppRole secret provider. It
publishes one complete private JSONFile source that Oxidized consumes without
contacting either authority service.

The initial population is exactly `netbox:dcim.device:1` and
`netbox:dcim.device:2`, ordered by positive object ID. Stable node names are
`netbox-device-1` and `netbox-device-2`, both in group `managed`. Device 3 is
rejected rather than ignored. Cisco IOS XE maps to `ios`; Junos maps to `junos`.
Both use explicit SSH port 22, so the Junos NCDP NETCONF port 830 never crosses
into the Oxidized source.

The dedicated `ncdp-oxidized-source` AppRole carries only policy
`ncdp-oxidized-device-read`, whose two exact paths grant read to device 1 and 2
credential objects. It is separate from Buildkite and local deployment
identities, binds bounded SecretIDs, suppresses default policy, and issues
short-lived one-use tokens.

All authority resolution and source validation completes in memory before a
mode-0600 same-directory temporary file is flushed, synchronized, and atomically
published. A failure leaves the prior valid cache untouched and reports
failure; whether a future service may consume stale cache is deferred.

## Consequences

The generated source is a private runtime cache, not desired state, inventory,
credential authority, audit evidence, or configuration history. It contains
only the seven fields required by JSONFile. Increment 10C-3 proves parsing with
polling disabled and performs no device connection or collection. Git output,
persistent service ownership, scheduling, forced collection, and audit runtime
publication remain later work.
