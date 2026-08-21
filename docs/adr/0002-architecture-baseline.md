# Architecture planes and technology baseline

**Status:** Accepted

**Date:** 2026-08-21

## Context

The platform needs clear authority, orchestration, execution, assurance, evidence,
and operations boundaries before integrations are implemented.

## Decision

GitHub owns code, policy, desired state, review, and history. Buildkite owns
workflow, gates, approvals, queues, concurrency, artifacts, and scheduling.
Docker owns reproducible runtime isolation. Python owns domain policy and control.
NetBox will own infrastructure identity, topology/IPAM relationships, platform,
role, tags, targeting, and inventory metadata; Git owns managed device-configuration
intent. No managed property is authoritative in both, and overlapping NetBox or
native fields require an explicit owner before automation consumes them. OpenBao
will exchange Buildkite OIDC for short-lived scoped credentials.

Ansible Core is the initial execution provider, with `cisco.ios` for IOS/IOS XE
and `juniper.device` plus PyEZ/NETCONF for Junos. Batfish provides offline
assurance. Terraform with CiscoDevNet CML2 owns CML lab lifecycle. pyATS/Genie
and JSNAPy/PyEZ provide vendor-aware live validation. Oxidized with Git records
configuration history. Prometheus, Grafana, Alertmanager, gNMIc,
OpenConfig/gNMI, SNMP Exporter, and Blackbox Exporter provide independent
observability. Alertmanager must route actionable alerts to at least one configured
demonstration notification receiver; the receiver is deferred. A platform-owned
typed `ChangeRecord` correlates change, artifact, inventory, plan, approval,
execution, validation, history, and recovery evidence.

Selection does not mean implementation in PR #1.

## Rationale

Function-based planes keep policy authoritative while allowing tools to evolve.
The selected ecosystem supports a self-hosted mixed-vendor reference lab.

## Consequences

Integrations require explicit adapters and normalized results. Observability is
independent of CI. Terraform never owns production device configuration.

## Deferred decisions

Concrete schemas, APIs, deployment topology, retention, artifact signing, and
service configuration await evidence from vertical increments.
