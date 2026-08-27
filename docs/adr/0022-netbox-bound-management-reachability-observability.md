# ADR 0022: NetBox-bound management-service reachability observability

## Status

Accepted for implementation. Increment 11A live CML acceptance is pending.

## Decision

Continuous observability is an independent, read-only operational plane. It is
not part of Buildkite deployment execution and cannot authorize a device write,
rollback, or remediation. NetBox remains the authority for the exact managed
population, stable object identity, management address, platform, and the
platform-derived automation service port. The existing inventory contract maps
Cisco IOS XE to SSH TCP/22 and Junos to NETCONF TCP/830; observability does not
maintain a second port or inventory mapping.

Prometheus retains operational time series and Blackbox Exporter performs only
credential-free TCP connects. A successful probe means only that the admitted
management-service endpoint accepted a TCP connection. It does not prove
authentication, hostname, protocol function, device health, or configuration
correctness. Neither service receives the NetBox token, CML credential, device
credential, SSH trust, configuration history, AuditStore, checkout, or Docker
socket.

The durable metric identity is the stable NetBox object identity. The private
address and port are used only as the Blackbox `target` parameter. The bounded
labels are `instance`, `device_name`, `platform`, `management_service`,
`telemetry_source`, and `environment`. CML UUIDs, build/request IDs, timestamps,
arbitrary tags, raw provider errors, IP addresses, and ports are prohibited as
durable labels. A NetBox rename may deliberately create label churn for
`device_name`; the stable `instance` remains authoritative and the bounded name
is retained for operator usability.

A disposable CML operator realization is an admission boundary, not inventory
or cryptographic session trust. Activation requires one exact operator lab, the
exact two BOOTED managed nodes, reviewed definitions/images, non-printing Day-0
name/address checks, a stopped legacy lab, no staging lab, and no competing
active owner of the fixed management addresses. UUIDs and admission digest are
kept only in private realization/readiness metadata. Oxidized host trust and the
user's SSH trust are unrelated and are never reused.

Private target state has explicit `ACTIVE`, `RETIRED`, `FAILED`, and `AMBIGUOUS`
semantics with closed failure classifications. An ACTIVE generation expires
unless CML and NetBox authority are revalidated. Canonical targets are published
atomically before status, under an ambiguity guard. Readiness binds the exact
target bytes and generation digest to the admitted realization, the exact
two-node population, current Prometheus and Blackbox containers, source commit,
and expiry. Authority or ambiguous publication failure removes live targets and
fails closed rather than retaining an ACTIVE authorization indefinitely.

Retirement invalidates readiness first, removes realization admission, publishes
and verifies an empty RETIRED file-discovery generation, and confirms that
Prometheus schedules no management probes before the CML twin may be destroyed.
Prometheus TSDB history is retained across target retirement and container
replacement.

Launchd owns a five-minute repository-independent reconciliation lifecycle;
Docker restart policy remains `no`. The versioned external runtime uses pinned
Linux/ARM64 images, a loopback-only Prometheus port, a private container network,
least-privilege container settings, and private external config/state roots.
Grafana, Alertmanager, SNMP, gNMI, OpenTelemetry, alerts, and automated
remediation are outside Increment 11A.

## Consequences

Reachability is useful but intentionally narrow. It establishes stable identity,
target authorization, private publication, persistent time-series retention, and
failure-safe retirement before richer telemetry is introduced. Configuration
bytes and diffs remain private Oxidized history; AuditStore remains delivery
evidence rather than a metrics database.
