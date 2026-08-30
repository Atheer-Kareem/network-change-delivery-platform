# Product contract

## Product statement and audiences

Network Change Delivery Platform is a greenfield, self-hosted reference system
for reviewed, validated, auditable, recoverable, and observable fleet changes.
It demonstrates enterprise NetDevOps delivery patterns to internal
network-automation stakeholders, future employers, and engineers learning from
a personal lab implementation.

Its goals are safe change intent, deterministic planning, vendor-aware
execution, fleet-aware rollout, independent validation, durable evidence,
recovery, and continuous monitoring. The implemented vendor scope is Cisco
IOS/IOS XE and Junos. Fortinet is deferred.

## Reference-environment and authority boundary

The implementation runs only in a personal MacBook and CML mini-PC lab. It is
not production-ready and must contain no company device, credential,
configuration, address, topology, internal document, or proprietary data.

Git is authoritative for code, policy, reviewed change requests, and managed
device-configuration intent. NetBox is authoritative for infrastructure
identity, topology and IPAM relationships, platforms, roles, tags,
target-selection data, and other inventory metadata. No managed property may be
authoritative in both systems. Before automation consumes an overlapping NetBox
or native device field, that property must have one explicit owner. Devices are
observed reality, not authoritative desired state.

## Intended lifecycle and fleet behaviour

A pull request proposes intent. Validation and policy precede complete target
resolution, immutable planning, assurance, risk classification, optional digital
twin testing, and approval. Immediately before writes, the system re-verifies
identity, relevant state, and the still-required change. It deploys one canary
per representative platform, then bounded waves, independently validating each
stage. Evidence and continuous monitoring follow.

Targets may be one device, explicit lists, selector-derived fleets, vendor-only
fleets, or mixed fleets. Resolution and preflight cover the complete frozen
fleet before the first write. Overlapping scopes are serialized or rejected.
No-op targets are recorded. Failure stops later waves and partial outcomes are
reported honestly; the system does not claim multi-device atomicity.

## Audit, recovery, and observability

Typed `ChangeRecord` and `FleetChangeRecord` evidence describes bounded device
and fleet execution. Append-only `ChangeAuditRecord` and
`ConfigurationObservationRecord` objects durably correlate those records by
identity and digest with change and PR identity, exact commit, Buildkite build,
inventory and frozen targets, immutable plans, approval, assurance, staging,
promotion, outcome, and private Oxidized chronology. They reference large
immutable artifacts instead of copying payloads and exclude credentials,
secret-bearing data, and full device configurations.

Immediate recovery uses the strongest proven mechanism for each vendor and
supported change; Cisco and Junos do not share identical transaction semantics.
A later rollback is represented as a new reviewed desired-state change through
the ordinary validation, staging, approval, deployment, and validation pipeline.
`git revert` may help produce that Git change, but Git history alone never
authorizes a device write. Automated historical ancestry reconstruction,
inverse-plan generation, and later-change conflict handling are deferred.
Continuous observability operates independently of pipeline completion.
Alertmanager routes actionable advisory alerts to a bounded private local
demonstration receiver; neither component has remediation authority.

## First vertical and acceptance outcomes

The first implemented vertical is managed interface descriptions across Cisco
IOS/IOS XE and Junos. Its contract requires reviewed vendor-neutral intent where
semantics genuinely match, frozen target and plan identity, complete preflight,
canary and wave controls, vendor-aware execution and recovery, independent
validation, honest outcomes, and correlated evidence without secrets.
NetBox identifies each device and interface and may supply targeting and safety
metadata. Git alone owns the desired device interface description; NetBox's
interface description field is not a second desired-state authority for this
vertical.

## Non-goals

Baseline 1 excludes production use, company infrastructure, Kubernetes, NSO,
Nornir initially, Nautobot, Infrahub, SuzieQ, containerlab, OPA, Terraform device
configuration, autonomous AI change, self-healing writes, credential
standardization or mass rotation, PR-supplied arbitrary CLI, full vendor feature
parity, universal transactions, automatic retry after uncertain writes,
protocol or endpoint fallback, fleet atomicity, HA clustering, generic dynamic
plugins, and any claim that the lab implementation moves unchanged to production.

## Relationship to network-automation-platform

This product is separate from `network-automation-platform`. That project's
V1.0.0 release and its V1.5 architecture baseline and CAT 8000V/NETCONF
feasibility work are complete. V1.5 production implementation is paused and has
not started. This repository does not modify, depend on, or copy that project.
