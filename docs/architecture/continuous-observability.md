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
deployment or automated remediation. Dashboards/alerts, SNMPv3, and gNMI are
separate later increments.
