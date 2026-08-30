# Increment 11C SNMPv3 interface telemetry

Increment 11C is split by authority. 11C-1, 11C-2, and 11C-3 are complete.
11C-4 persistent live exporter activation and polling is deferred. ADR 0026 is
therefore accepted through 11C-3 rather than accepted without qualification.

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
Prometheus and the exporter alone share an internal control network. The
exporter and two disposable agents alone share a separate non-internal device
bridge, proving the intended HTTP-control and UDP-polling separation without
claiming live-router reachability.

The synthetic verifier exercises valid polling plus wrong authentication,
wrong privacy, unknown selector, unreachable target, and one-target isolation.
It verifies reviewed IF-MIB metrics through Prometheus, exact NetBox-style
device/interface normalization, unmatched-row dropping, device-scalar
retention, and preservation of the independent 11A/11B path.

Random credentials exist only in disposable private agent and exporter files.
The auth directory is mode 0700 and the active auth-only file mode 0600. Atomic
generation replacement is followed by private `POST /-/reload`; successful
rotation preserves the exporter container ID. Invalid replacement returns HTTP
500 and leaves the previous valid configuration active.

Authentication and privacy passphrases are absent from Docker inspection,
environment, arguments, Prometheus configuration, targets, metrics, ordinary
logs, output, and durable evidence. The private exporter `/config` endpoint
redacts them. The controlled SNMPv3 username is also absent from Prometheus
configuration, target and metric labels, environment, arguments, ordinary logs,
and public evidence.

11C-2 provides synthetic evidence only. It does not prove Docker
Desktop-to-live-router UDP/161 reachability or activate the persistent runtime.

## 11C-3 implementation preparation

11C-3 first implemented the offline credential-authority,
immutable-generation, typed-plan, vendor-rendering, targeted-preflight,
recovery, and protected-path contracts. `v1` is an exact create-only generation
for each logical device. Buildkite provisioning JWT policies are exact-path and
device-specific. Mocked OpenBao tests proved device/path separation, no default
policy, one-use clients, create-only behavior, schema validation, and
secret-safe failures.

The existing `deploy-gate` remained the only live write boundary. An SNMP plan
uses the existing SSH/NETCONF OIDC capability plus a separate SNMP-only OIDC
capability acquired after fresh structural preflight and the pre-write audit
gate. Cisco and Junos implementations render secrets only in process, reduce
post-state to bounded facts, and preserve unrelated SNMP configuration.

That preparation was not itself live acceptance. It was followed by separately
reviewed Cisco and Junos commit/build/authorization paths; historical failed
attempts were never retried.

## 11C-3 protected live closure

### Cisco IOS XE

- Build: #267
- Change ID: `CHG-SNMP-11C3-CISCO-004`
- Final outcome: `SUCCEEDED`
- Device write: yes
- AuditStore record: `01a050b6-6d7d-4294-990a-0f82ed978409`
- Audit digest:
  `sha256:be3f37c27f42cfbdb982003ae13004f7dff36a3ef52a7877f657aabf450c0ff3`

The protected Cisco path used fresh targeted preflight, the exact approved
create-only SNMP intent, independent normalized post-validation, and the
existing bounded targeted-inverse recovery contract. Successful evidence did
not require recovery.

### Junos

- Build: #275
- Change ID: `CHG-SNMP-11C3-JUNOS-001`
- Plan digest:
  `sha256:3d07ea20778999dc67b9963d7443427b5125b0892ba0503f37dbc8188a19d7f6`
- Final outcome: `SUCCEEDED`
- Device write: yes
- AuditStore record: `01a0513c-9d87-4faf-8108-9029c5f44c49`
- Audit digest:
  `sha256:c389713198d4cb6f3f97404a101ea2e6f6e730f925f4ce7b35debb48051858c4`

Before live `.20` execution, the exact Junos source plan passed disposable
`.40` rehearsal through the production transaction path. Live execution
preserved the Junos exclusive candidate, commit check, commit-confirmed,
independent validation, and confirmation safety semantics.

Build #273 is retained as meaningful fail-closed evidence. Its OpenBao JWT
authorization failed before credential read, NETCONF preflight, or device
write. The historical job was never retried. A fresh commit, Build #275, and
fresh human authorization produced the accepted success.

## Current boundary

**11C-3 COMPLETE.**

**11C-4 DEFERRED.**

The accepted persistent observability runtime remains the existing five-service
11A/11B runtime and remains SNMP-free. This record does not claim persistent
live SNMP polling, Docker-to-live-router SNMP polling acceptance, or the current
external state of the deferred observability-source AppRole.
