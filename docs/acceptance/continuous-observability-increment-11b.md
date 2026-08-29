# Increment 11B-1 dashboards and operator alerts

This increment adds a provisioned Grafana reachability dashboard, reviewed
Prometheus rules, Alertmanager routing, and a bounded local demonstration
receiver. It is accepted offline/container-first; final merged-main live 11B
acceptance is pending.

Grafana is loopback-only and viewer-only. Alertmanager and the receiver are
private-network consumers. None has device, NetBox, OpenBao, CML, Oxidized,
AuditStore, Docker, deployment, rollback, or remediation authority.

The rules distinguish endpoint TCP failure (`probe_success == 0`), missing
target samples, and Blackbox exporter scrape failure. Alert labels use only
bounded existing identity/component labels. No raw endpoint, CML UUID, build
ID, request ID, or provider text is persisted as identity.

`11B ACCEPTANCE: PENDING MERGED-MAIN LIVE VALIDATION`
