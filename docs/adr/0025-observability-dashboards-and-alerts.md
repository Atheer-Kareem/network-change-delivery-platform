# ADR 0025: Observability dashboards and operator alerts

Status: proposed (11B-1)

Grafana and Alertmanager consume the read-only 11A Prometheus/Blackbox
metrics. Grafana serves a Git-provisioned viewer dashboard on loopback;
Alertmanager routes bounded advisory alerts to a private local demonstration
receiver. Neither component receives credentials or remediation authority, and
alerts never execute network changes. SNMPv3 and gNMI remain separate future
increments.
