# ADR 0026: SNMPv3 interface telemetry contract

## Status

Proposed

## Context

Accepted Increments 11A and 11B provide independent TCP management-service
reachability, dashboards, and operator-only alerts through a persistent
five-service observability runtime. They do not collect interface state or
counters. Roadmap Increment 11C adds that bounded telemetry without granting the
observability plane inventory, configuration, deployment, or remediation
authority. Increment 11D gNMI/OpenConfig streaming telemetry remains separate.

The two admitted managed devices support SNMPv3 user-based security and
view-based access control with one common strong profile: authentication and
privacy (`authPriv`), SHA256 authentication, and AES128 privacy. Neither device
currently has SNMP configured; live provisioning and collection are not evidence
for this offline decision.

SNMP interface rows are indexed by `ifIndex`, whose value can change when an
agent is reinitialized. NetBox already owns stable numeric device and interface
object identity. The architecture therefore needs an exact, bounded join rather
than treating an agent-local index, alias, or description as durable identity.

## Decision

11C is limited to authenticated, encrypted, read-only SNMPv3 interface
telemetry. The common device security profile is `authPriv` with SHA256 and
AES128. Communities, SNMPv1/v2c, traps, notifications, `SET`, write views,
vendor MIBs, arbitrary MIB collection, and remediation are excluded.

The reviewed module is `ncdp_if_mib`, generated with upstream
`snmp_exporter`/generator v0.30.1. Its exact protocol-access closure is:

| Object | Access OID |
| --- | --- |
| `sysUpTime.0` | `1.3.6.1.2.1.1.3.0` |
| `ifNumber.0` | `1.3.6.1.2.1.2.1.0` |
| `ifIndex` | `1.3.6.1.2.1.2.2.1.1` |
| `ifAdminStatus` | `1.3.6.1.2.1.2.2.1.7` |
| `ifOperStatus` | `1.3.6.1.2.1.2.2.1.8` |
| `ifInDiscards` | `1.3.6.1.2.1.2.2.1.13` |
| `ifInErrors` | `1.3.6.1.2.1.2.2.1.14` |
| `ifOutDiscards` | `1.3.6.1.2.1.2.2.1.19` |
| `ifOutErrors` | `1.3.6.1.2.1.2.2.1.20` |
| `ifName` | `1.3.6.1.2.1.31.1.1.1.1` |
| `ifHCInOctets` | `1.3.6.1.2.1.31.1.1.1.6` |
| `ifHCOutOctets` | `1.3.6.1.2.1.31.1.1.1.10` |
| `ifHighSpeed` | `1.3.6.1.2.1.31.1.1.1.15` |
| `ifCounterDiscontinuityTime` | `1.3.6.1.2.1.31.1.1.1.19` |
| `ifTableLastChange.0` | `1.3.6.1.2.1.31.1.5.0` |

The future Cisco view and Junos VACM read view must correspond to this exact
closure, not a generic IF-MIB subtree. A reviewed generator change that expands
or contracts the closure requires a matching reviewed device-view change.
Device-view validation uses the base object OID for each scalar while the
exporter performs the generated `.0` instance GET shown above.
`ifName` is collected as the lookup label for table metrics; it is not emitted as
a standalone numeric metric. The 32-bit traffic octet counters are excluded in
favor of `ifHCInOctets` and `ifHCOutOctets`. Reset and discontinuity primitives
are collected, but rate calculations, dashboards, and alerts are later work.

NetBox remains inventory authority. A target retains
`netbox:dcim.device:<id>`, and the durable interface identity is
`netbox:dcim.interface:<id>`. Eligibility starts from each admitted managed
device's bounded NetBox-modeled interface population. Every interface requires a
stable numeric NetBox ID and exact non-empty name. Resolution uses case-sensitive
exact `ifName` equality. `ifIndex` is transient observation only; fuzzy names,
`ifDescr`, `ifAlias`, MAC addresses, and IP addresses cannot establish durable
identity. Duplicate IDs, duplicate names, malformed or unbounded populations,
missing expected rows, and ambiguous observed rows fail closed. SNMP-only rows
are not promoted into managed identity.

Prometheus remains metrics authority. A future `snmp_exporter` is only a
protocol translator on this conceptual path:

```text
Prometheus -> snmp_exporter -> UDP/161 -> admitted device
```

It will be a sixth service in the existing Compose project, with no host port and
a dedicated private network shared only with Prometheus. It will not receive
NetBox, CML, OpenBao bootstrap, SSH, AuditStore, or device-write authority. Its
future private authentication input is a mode-0600 file atomically replaced by a
host materializer inside a mode-0700 directory. The directory, rather than one
rotating file, is mounted read-only, and successful publication requires an
explicit exporter reload or reconciliation. Environment-variable secret
injection is rejected because container inspection exposes environment values.

SNMP target generation and readiness are separate from
`ObservabilityReady(service_contract="11A")`. SNMP state distinguishes ACTIVE,
DEGRADED, RETIRED, FAILED, and AMBIGUOUS outcomes. A per-device SNMP failure must
not invalidate existing TCP reachability or remove another device's valid SNMP
identity without a separate population/realization failure.

Each logical device will use a separate versioned SNMP credential. Authentication
and privacy values are secret; SSH and SNMP credentials remain separate.
Device-provisioning secret-read authority and observability source authority are
also separate. Secret values never enter plans, evidence, Git, container
environment, Prometheus configuration, or metric labels. This ADR does not select
or create real OpenBao paths, roles, policies, AppRoles, bootstrap values, or
device credentials.
The bounded auth selector is a non-secret routing value that may later populate
`__param_auth`; it is neither credential material nor durable metric identity.

## Delivery decomposition

11C is divided by authority and evidence boundary:

1. **11C-1 — architecture and offline contract:** proposed ADR, generated
   standard-IETF module, pure typed identity/state contracts, closure validation,
   and unit tests. No SNMP, secret-provider, device, or persistent-runtime access.
2. **11C-2 — exporter and synthetic integration:** disposable SNMPv3 agent,
   sixth-service container/runtime contract, synthetic `authPriv` collection,
   Prometheus normalization, and secret-leak tests. It introduces no real OpenBao
   or device authority.
3. **11C-3 — credential and device provisioning:** real SNMP credential storage,
   separate provisioning and observability secret-read identities, typed
   vendor-specific device intent, and separately authorized device mutation.
4. **11C-4 — persistent live activation and acceptance:** supported service
   update and read-only Cisco/Junos telemetry acceptance while preserving 11A/11B.

Later slices are not implemented or accepted by this decision. ADR status remains
Proposed until the required implementation and live acceptance evidence exists.

## Consequences

The first SNMP slice is reproducible and reviewable without using live devices as
a debugger. Stable identity survives `ifIndex` changes, and the generated module
cannot silently expand device read authority. The later runtime must add a
separate private auth lifecycle and sixth-service verification, while the later
device slice must implement honest vendor-specific provisioning and recovery.

The exact Cisco interface rows, UDP/161 Docker reachability, scrape timing, and
credential failure behavior remain evidence for later synthetic or explicitly
authorized live slices. No SNMP configuration, collection, OpenBao mutation,
NetBox mutation, CML mutation, or persistent-service change is authorized here.
