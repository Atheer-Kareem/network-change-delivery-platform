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

It will be a sixth service in the existing Compose project, with no host port.
An internal control network shared only by Prometheus and the exporter carries
Prometheus-to-exporter HTTP. A separate ordinary bridge attaches only the
exporter in the future production topology and provides exporter-to-device
UDP/161 egress; Prometheus and the other accepted services do not join it. It
will not receive NetBox, CML, OpenBao bootstrap, SSH, AuditStore, or device-write
authority. Its future private authentication input is a mode-0600 file
atomically replaced by a host materializer inside a mode-0700 directory. The
directory, rather than one rotating file, is mounted read-only, and successful
publication requires an explicit exporter reload or reconciliation.
Environment-variable secret injection is rejected because container inspection
exposes environment values. 11C-2 implements that two-network topology only as
an explicitly selected Compose overlay; synthetic agents join only the device
bridge. The accepted five-service production invocation remains unchanged.
Synthetic rotation uses a private `POST /-/reload`, whose HTTP result provides
positive acknowledgement without publishing another host port. A rejected
reload retains the previously active valid exporter configuration. Synthetic
flow does not prove Docker Desktop-to-router UDP/161 reachability; that remains
11C-4 live evidence after separately approved provisioning.

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
The SNMPv3 username is likewise a non-secret but controlled authentication
principal. It may appear in the private auth file and the exporter's private
`/config` response, but not in Prometheus configuration, target or metric labels,
container environment or arguments, ordinary logs, or public evidence. Only the
authentication and privacy passphrases or keys are confidentiality-bearing;
`snmp_exporter` must redact those values from `/config`.

11C-3 fixes the first generation at `v1`. The non-secret principals are
`ncdp_snmp_d1_v1` and `ncdp_snmp_d2_v1`; both satisfy the reviewed IOS XE and
Junos 32-character naming bounds. Immutable OpenBao logical paths are
`ncdp/devices/1/snmpv3/v1` and `ncdp/devices/2/snmpv3/v1`. Each record contains
only the controlled username plus independently generated authentication and
privacy passphrases. Protocol choices remain code and plan policy rather than
mutable secret data. A later rotation creates a new generation and principal;
it never overwrites `v1` or aliases authority through a mutable `current` path.

Protected provisioning remains inside the existing commit-changed live request,
promotion, approval, and sole `deploy-gate`. The job uses the existing exact
device SSH/NETCONF role and a second, separate OIDC exchange for one exact
device/generation SNMP read role. The SNMP capability is requested only after
secret-free identity, plan, device-structure, and pre-write audit checks. It
cannot read SSH. The SSH capability cannot read SNMP. No new write job, approval
block, local administrative device-write command, fleet write, or automatic
retry is introduced. The read-only `snmp-provisioning-plan` command creates the
typed plan after NetBox resolution and targeted device preflight; it cannot
acquire an SNMP secret or execute a device write.

The future persistent materializer uses a separate AppRole that can read only
the two approved `v1` paths. Its bootstrap can issue only a bounded SecretID for
that source role; every source login produces one short, one-use client token
for one exact device read. It has no SSH, CML, NetBox, AuditStore, default-policy,
list, or write capability. 11C-3 implements and tests these resources and their
three-file private bootstrap contract (`bootstrap-role-id`,
`bootstrap-secret-id`, and `source-role-id`) offline; it does not configure
OpenBao. Provisioning JWT tokens are limited to 300 seconds and one use. A
source SecretID is limited to 1,800 seconds and two logins (one per exact device
read), while each resulting source client token is limited to 300 seconds and
one use. The private machine bootstrap can issue only source-role SecretIDs;
each bootstrap login yields a 60-second, one-use issuer token.

Device objects use deterministic names `NCDP_IFMIB`, `NCDP_SNMP_RO`, and the
versioned principal. A targeted preflight classifies the owned names as ABSENT,
EXACT_NCDP_STATE, or CONFLICT while preserving unrelated FOREIGN SNMP state.
The initial provisioning plan is created only from ABSENT owned names. An
existing user cannot be called idempotently correct because neither platform
can prove its original passphrases through a secret-free configuration read.
Conflicts fail closed and recovery removes only objects created by that exact
plan. Junos also requires a stable existing local engine identity because its
stored USM keys are engine-localized; this intent does not change engine ID.
For Cisco IOS XE, first provisioning may instead begin from the exact bounded
`%SNMP agent not enabled` response: the first reviewed `snmp-server` command
enables the agent and establishes its normal local engine identity. No explicit
engine-ID command is added. Cisco post-validation remains strict and requires
the resulting engine identity plus the exact owned view, group, and user;
Junos retains its pre-existing engine-identity requirement.

## Delivery decomposition

11C is divided by authority and evidence boundary:

1. **11C-1 — architecture and offline contract:** proposed ADR, generated
   standard-IETF module, pure typed identity/state contracts, closure validation,
   and unit tests. This slice is complete. It used no SNMP, secret-provider,
   device, or persistent-runtime access.
2. **11C-2 — exporter and synthetic integration:** disposable SNMPv3 agent,
   sixth-service container/runtime contract, synthetic `authPriv` collection,
   Prometheus normalization, rotation, and secret-leak tests. The implementation
   uses an opt-in overlay and introduces no real OpenBao, device, or persistent
   runtime authority.
3. **11C-3 — credential and device provisioning:** real SNMP credential storage,
   separate provisioning and observability secret-read identities, typed
   vendor-specific device intent, and separately authorized device mutation.
   The offline implementation and protected-path preparation exist, but no real
   OpenBao resource, credential, or device object has been created. Live closure
   requires separate future Cisco and Junos commit-bound changes.
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

## Vendor references

- Cisco IOS XE 17 SNMP configuration and command references specify
  `snmp-server user ... auth sha-2 256 ... priv aes 128`, privacy-level groups,
  read views, and `show snmp user` verification:
  <https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/snmp/configuration/xe-17-x/snmp-xe-17-book.html>
- Juniper documents `authentication-sha256`, `privacy-aes128`, USM/VACM
  security-to-group mapping, privacy-level read views, and engine-ID key
  localization:
  <https://www.juniper.net/documentation/us/en/software/junos/network-mgmt/topics/topic-map/configure-snmpv3.html>
  and
  <https://www.juniper.net/documentation/us/en/software/junos/network-mgmt/topics/topic-map/configure-the-local-engine-id.html>.
