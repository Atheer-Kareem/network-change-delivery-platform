# Increment 11B-1 dashboards and operator alerts

This increment adds a provisioned Grafana reachability dashboard, reviewed
Prometheus rules, Alertmanager routing, and a bounded local demonstration
receiver. Container-first acceptance and final merged-main persistent-runtime
acceptance are complete.

Grafana is loopback-only and viewer-only. Alertmanager and the receiver are
private-network consumers. None has device, NetBox, OpenBao, CML, Oxidized,
AuditStore, Docker, deployment, rollback, or remediation authority.

The rules distinguish endpoint TCP failure (`probe_success == 0`), missing
target samples, and Blackbox exporter scrape failure. Alert labels use only
bounded existing identity/component labels. No raw endpoint, CML UUID, build
ID, request ID, or provider text is persisted as identity.

## Merged-main evidence

PR #83 merged as commit `f75b9e9c274a2f2890116cc4c18592c97956c220`.
Natural merged-main Buildkite Build #231 passed on that exact commit. Its
isolated Docker acceptance exercised the production five-container verifier
and proved the reviewed alert FIRING/RESOLVED lifecycle without disrupting the
persistent live targets.

## Persistent 11A-to-11B transition

The accepted 11A installation at source commit
`47a6a856ccc19903b585d2a2605dbea3c67db616` was coherent before update: its
LaunchAgent last exit was zero, ACTIVE readiness bound exactly NetBox devices
1 and 2, both management TCP probes were successful, and the old production
two-container contract passed. No update guard or transition lock existed.

The supported update path installed the exact merged-main runtime without
changing the existing authority or NetBox token files. All five reviewed
digest-pinned Linux/ARM64 images and private image-ID records matched. Static
rules, Alertmanager, Grafana, and receiver assets were byte-identical to the
merged tree; writable Grafana and Alertmanager roots remained private.

One production LaunchAgent execution advanced its run count from 311 to 312,
completed with exit zero, and republished ACTIVE readiness for the merged-main
source commit. The production verifier accepted exactly Prometheus, Blackbox
Exporter, Grafana, Alertmanager, and the demonstration receiver with the
reviewed project, network, image, UID/GID, read-only-root, capability,
no-new-privileges, bind, and loopback-publication contracts.

Both admitted targets remained healthy (`core-02` SSH and `edge-junos-01`
NETCONF), with `probe_success == 1` and the Blackbox scrape pipeline up.
Grafana health and its provisioned read-only default Prometheus datasource
passed; the immutable `NCDP Management Reachability` dashboard was present in
folder `NCDP`. Prometheus loaded all three reviewed rules with health `ok` and
state `inactive` under the normal healthy live condition:

- `NCDPManagementServiceDown`;
- `NCDPManagementTargetsStale`; and
- `NCDPBlackboxPipelineDown`.

Prometheus discovered the private Alertmanager endpoint. Alertmanager was
ready on the private observability network and exposed only the reviewed
`ncdp-demonstration` receiver. The bounded receiver was private and running;
there were no active live alerts. No outage was induced. FIRING and recovery
remain supported by the isolated merged-main acceptance evidence, not by a
manufactured live failure.

A controlled restart of Prometheus, Grafana, and Alertmanager preserved the
existing Prometheus blocks and query history, the Grafana database and
provisioned dashboard, and Alertmanager's private state. The post-restart
production verifier and health checks passed.

Device configuration writes, CML mutations, NetBox mutations, OpenBao access,
deployment actions, and historical Buildkite retries were all zero. Existing
observability history was preserved, and no credential or secret value was
recorded in acceptance evidence.

`11B ACCEPTANCE: PASS`
