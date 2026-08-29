# Continuous observability

Increment 11A establishes an independent read-only observability plane for the
automation management service selected by NetBox. It does not participate in
planning, approval, deployment, recovery, or audit authority.

## Data and authority flow

```text
NetBox managed population ─┐
                           ├─> bounded materializer ─> private file_sd targets
CML live admission ────────┘                              │
                                                          v
Prometheus (stable NetBox labels) ─> Blackbox TCP connect ─> admitted endpoint
```

`NetBoxInventoryProvider` supplies the exact `ncdp-managed` population and the
existing `InventoryDevice` endpoint contract. Current Cisco IOS XE resolves to
SSH on port 22 and Junos resolves to NETCONF on port 830. Blackbox receives the
private `host:port` only through `__param_target`; relabeling preserves
`instance="netbox:dcim.device:<id>"`. TCP success has no stronger meaning than
connection acceptance.

CML admission independently proves that those addresses belong to exact lab
UUID `09605569-0468-4fc4-8684-beb5a1342b9c`, titled `NCDP Live`, in running
state. Admission uses private CML API authority, exact node UUIDs, definitions,
images, BOOTED state, and stored Day-0 identity markers. A valid ephemeral
`NCDP Staging ...` lab at `.30/.40` may coexist; every other active router
realization is still inspected and rejected if it claims live `.14/.20`.
These values do not become metric labels. No device credential, OpenBao device
secret, SSH key, NETCONF session, CLI command, or Oxidized trust is involved.

## Runtime and private state

The installed service uses these external roots:

* `/Users/netdevops/.config/ncdp/observability` for mode-0600 service config and
  host-side authority inputs;
* `/Users/netdevops/.local/state/ncdp/observability` for private status,
  discovery, logs, readiness, realization admission, and persistent TSDB;
* `/Users/netdevops/.local/lib/ncdp/observability-service-<commit>` for a
  non-editable versioned wheel and Compose definition.

Parent directories are mode 0700. Private files are regular, mode 0600,
single-link, bounded, canonical, and atomically replaced. Publication ambiguity
leaves a private marker and blocks readiness. Prometheus sees only the discovery
directory; it does not see the NetBox token, CML authority, realization record,
or readiness.

Prometheus 3.14.0 retains 15 days or 1 GB, whichever bound is reached first, at
`127.0.0.1:9090`. Blackbox Exporter 0.27.0 is reachable only on the private
container network. Both images are immutable digest pins with Linux/ARM64
manifests. Containers run as the current non-root UID/GID, with read-only root
filesystems, all capabilities dropped, `no-new-privileges`, no Docker socket,
and only reviewed mounts. Launchd reconciles every 300 seconds; container restart
policies are `no`.

Runtime updates use one exclusive transition lock shared with reconciliation.
The updater invalidates readiness before switching any live pointer, retains an
update-in-progress marker until the config and entrypoint switch completes, and
leaves both controls fail closed after an interrupted update. The versioned
entrypoint exports its immutable source commit; reconciliation requires it to
equal the private `source-commit` before operating and immediately before
readiness publication. Readiness readers require the expected commit as an
independent argument and never infer it from the marker.

## State and failure semantics

ACTIVE means the exact unexpired realization and NetBox population were
revalidated and the target generation is bound into current service readiness.
RETIRED means probe scheduling is intentionally empty. FAILED and AMBIGUOUS use
closed classifications and an empty target file; arbitrary provider responses
are never persisted or logged.

When no admitted live realization exists, reconciliation preserves Prometheus
history while publishing RETIRED empty discovery. NetBox or CML failure
invalidates readiness and removes live targets. A changed realization cannot
inherit prior authorization: a new admission and generation are required.

Safe retirement remains independently testable and its order is
safety-significant:

1. invalidate readiness;
2. retire realization admission;
3. publish and verify empty RETIRED discovery;
4. verify Prometheus has no management-service targets;
5. verify durable TSDB history remains available.

Successful final 11A acceptance does not retire these targets or stop
`NCDP Live`; ACTIVE reconciliation is the intended steady state.

## Boundaries

Prometheus is not inventory authority, Oxidized configuration history, or
AuditStore. Metrics contain no configuration, diff, credential, arbitrary error,
or high-cardinality ephemeral identity. Observability cannot invoke NCDP
deployment or automated remediation. SNMPv3 and gNMI are separate later
increments.
11B-1 adds Grafana and Alertmanager as read-only consumers of these metrics.
Grafana is provisioned from reviewed files and exposed only on loopback;
Alertmanager routes advisory alerts to a private bounded demonstration
receiver. Neither service has credentials, device access, or remediation
authority.

## Proposed 11C SNMPv3 boundary

ADR 0026 proposes an offline contract for the next independent path:

```text
11A: Prometheus -> Blackbox TCP probe -> admitted management service
11C: Prometheus -> snmp_exporter -> UDP/161 -> admitted device
```

The accepted production runtime remains the five 11B services. 11C-2 adds an
explicitly selected synthetic Compose overlay that attaches Prometheus and a
sixth `snmp_exporter` service to a dedicated internal network. Ordinary base
Compose invocation, installation, update, LaunchAgent reconciliation, and live
Prometheus configuration remain five-service and SNMP-free. The overlay must not
make the 11A target generation or
`ObservabilityReady(service_contract="11A")` depend on SNMP health.

The future exporter is a protocol translator, not inventory authority. NetBox
continues to own stable device identity and stable numeric interface object
identity. The host will start from a conservatively bounded NetBox-modeled
interface population and map each expected interface through case-sensitive
exact `ifName` equality. `netbox:dcim.interface:<id>` is durable; `ifIndex` is
transient. Duplicate IDs or names, missing or ambiguous matches, malformed
relationships, pagination failure, and excessive populations fail closed.
SNMP-only interfaces never acquire managed identity merely because an agent
reports them.

The future exporter will have no host port and will share a dedicated private
Docker network only with Prometheus. It will not receive the NetBox token, CML
authority, OpenBao bootstrap, SSH credentials, AuditStore, configuration
history, or device-write capability. Its private authentication directory will
be mounted read-only. A host materializer will eventually replace a mode-0600
auth file atomically inside that mode-0700 directory and then deliberately reload
or reconcile the exporter. Synthetic evidence selects a private
`POST /-/reload`: successful replacement is acknowledged without restarting the
container, while a rejected reload leaves the prior valid configuration active.
Real materialization, OpenBao identity, and device provisioning remain 11C-3.

Authentication and privacy passphrases or keys are secret. The SNMPv3 username,
auth selector, and versioned credential reference are non-secret controlled
identity. The private exporter `/config` response may contain the username but
must redact both passphrases. Usernames remain forbidden from Prometheus config,
targets, metric labels, container environment and arguments, ordinary logs, and
public evidence. The exporter has no host-published port, so `/config` remains
reachable only on the dedicated private network.

The reviewed `ncdp_if_mib` generator source and generated module use only the
exact system and interface objects recorded by ADR 0026. The future Cisco and
Junos read views must match that generated get/walk closure. Expanding the
module requires a corresponding reviewed device-view change; broad IF-MIB
authority is not implied. SNMPv3 communities, traps, write access, vendor MIBs,
dashboards, alerts, rates, and remediation remain outside 11C. gNMI remains 11D.
