# ADR 0025: Observability dashboards and operator alerts

Status: accepted (11B-1)

Grafana and Alertmanager consume the read-only 11A Prometheus/Blackbox
metrics. Grafana serves a Git-provisioned viewer dashboard on loopback;
Alertmanager routes bounded advisory alerts to a private local demonstration
receiver. Neither component receives credentials or remediation authority, and
alerts never execute network changes. SNMPv3 and gNMI remain separate future
increments.

Acceptance is bound to merged-main commit
`f75b9e9c274a2f2890116cc4c18592c97956c220`. Buildkite Build #231 passed the
isolated five-service runtime, rule, notification, recovery, and persistence
checks. Subsequent non-disruptive persistent-runtime acceptance transitioned
the accepted 11A installation through the supported update path, republished
fresh ACTIVE readiness, verified both live TCP targets, and accepted the exact
five-container production contract. All live rules were healthy and inactive;
no live outage was induced. Device writes, CML/NetBox mutations, OpenBao access,
deployment, and remediation remained zero.
