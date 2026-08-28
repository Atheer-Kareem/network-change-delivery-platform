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

This credential-free observability boundary does not supersede ADR 0013.
Credentials used to establish a CML realization remain outside the observability
plane; Prometheus, Blackbox, admission, and reconciliation never receive them.

The durable metric identity is the stable NetBox object identity. The private
address and port are used only as the Blackbox `target` parameter. The bounded
labels are `instance`, `device_name`, `platform`, `management_service`,
`telemetry_source`, and `environment`. CML UUIDs, build/request IDs, timestamps,
arbitrary tags, raw provider errors, IP addresses, and ports are prohibited as
durable labels. A NetBox rename may deliberately create label churn for
`device_name`; the stable `instance` remains authoritative and the bounded name
is retained for operator usability.

ADR 0024 makes the persistent, manually owned live realization the admission
boundary; it is not inventory or cryptographic session trust. Activation binds
exact lab UUID `09605569-0468-4fc4-8684-beb5a1342b9c`, title `NCDP Live`, and
running state. It requires the exact two BOOTED managed routers: NetBox device 1
`core-02` at `.14` using the accepted CAT8000V definition/image, and NetBox
device 2 `edge-junos-01` at `.20` using the accepted vJunos definition/image.
Non-printing stored Day-0 checks bind each logical hostname and address.

Ephemeral `NCDP Staging ...` labs use `.30/.40` and may coexist with live
admission. Every other active router realization, including staging, remains
subject to collision inspection and is rejected if it claims `.14` or `.20`.
The live UUID and admission digest are kept only in private
realization/readiness metadata. Oxidized host trust and the user's SSH trust are
unrelated and are never reused.

Private target state has explicit `ACTIVE`, `RETIRED`, `FAILED`, and `AMBIGUOUS`
semantics with closed failure classifications. An ACTIVE generation expires
unless CML and NetBox authority are revalidated. Canonical targets are published
atomically before status, under an ambiguity guard. Readiness binds the exact
target bytes and generation digest to the admitted realization, the exact
two-node population, current Prometheus and Blackbox containers, source commit,
and expiry. Authority or ambiguous publication failure removes live targets and
fails closed rather than retaining an ACTIVE authorization indefinitely.

The source-commit value is enforced, not merely recorded. The executing
versioned runtime must equal the private installed-runtime `source-commit`, and
readiness verification receives that expected commit independently. Runtime
update and reconciliation share an exclusive transition lock; updates invalidate
readiness before moving live pointers and retain a blocking ambiguity marker
until the new config and entrypoint are coherent.

Retirement invalidates readiness first, removes realization admission, publishes
and verifies an empty RETIRED file-discovery generation, and confirms that
Prometheus schedules no management probes. This safe retirement capability does
not authorize stopping or destroying `NCDP Live`. Prometheus TSDB history is
retained across target retirement and container replacement.

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
