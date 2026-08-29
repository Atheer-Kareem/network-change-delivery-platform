# Increment 11C SNMPv3 interface telemetry

Increment 11C is deliberately split by authority. ADR 0026 remains Proposed:
no real SNMP credential, router configuration, live polling, OpenBao authority,
or persistent observability activation has been accepted.

## 11C-1 offline contract

11C-1 closed on merged-main commit
`ccb6db2f9bd178553dc841883c289cb1f5c9007b`; natural Buildkite Build #237
passed on that exact commit. It established the reviewed `ncdp_if_mib` closure,
reproducible generator provenance, stable NetBox-owned interface identity,
transient-only `ifIndex`, and bounded fail-closed offline models.

## 11C-2 synthetic integration evidence

11C-2 adds an explicitly selected Compose overlay; the accepted five-service
production invocation remains unchanged. Disposable Linux/ARM64 Net-SNMP 5.9.3
agents prove SNMPv3 `authPriv` with SHA256 authentication and AES128 privacy
against the exact digest-pinned `snmp_exporter` v0.30.1 image.
Prometheus and the exporter alone share an internal control network. The exporter
and two disposable agents alone share a separate non-internal device bridge,
proving the intended HTTP-control and UDP-polling separation without claiming
live-router reachability.

The synthetic verifier exercises valid polling plus wrong authentication,
wrong privacy, unknown selector, unreachable target, and one-target isolation
cases. It verifies the reviewed IF-MIB metrics through Prometheus, exact
NetBox-style device and interface normalization, unmatched-row dropping,
device-scalar retention, and preservation of the independent 11A/11B path.

Random credentials exist only in disposable private agent and exporter files.
The auth directory is mode 0700 and the active auth-only file mode 0600. Atomic
generation replacement is followed by private `POST /-/reload`; successful
rotation preserves the exporter container ID. Invalid replacement returns HTTP
500 and leaves the previous valid configuration active.

Authentication and privacy passphrases are absent from Docker inspection,
environment, arguments, Prometheus configuration, targets, metrics, ordinary
logs, output, and durable evidence. The private exporter `/config` endpoint
redacts them. Its SNMPv3 username is classified as non-secret controlled
identity: it is expected in the private auth representation but is absent from
Prometheus configuration, target and metric labels, environment, arguments,
ordinary logs, and public evidence.

11C-2 provides synthetic evidence only. Real OpenBao identities and credentials,
typed Cisco/Junos provisioning, device mutation, persistent activation, actual
Docker Desktop-to-router UDP/161 reachability, and live read-only acceptance
remain 11C-3 and 11C-4.
