# Architecture overview

Architecture is organized around functions and contracts, not permanent tool
coupling. Policy flows from reviewed intent toward increasingly privileged
operations; observations and evidence flow back without secrets.

```mermaid
flowchart LR
  GH[Change plane\nGitHub] --> BK[Workflow plane\nBuildkite]
  BK --> PY[Control plane\nPython]
  NB[Source of truth\nNetBox] --> PY
  OB[Secrets\nOpenBao] --> EX[Execution\nAnsible + vendor adapters]
  PY --> BA[Assurance\nBatfish]
  PY --> DT[Digital twin\nTerraform + CML]
  PY --> EX
  EX --> LV[Live validation\npyATS / JSNAPy]
  PY --> EV[Audit evidence\nChangeRecord]
  EX --> EV
  LV --> EV
  OX[Configuration history\nOxidized] --> EV
  NB --> OBS[Continuous observability\nPrometheus ecosystem]
  DK[Runtime plane\nDocker] -. isolates .-> BK
  DK -. packages .-> PY
```

## Planes and responsibilities

- **Change:** GitHub stores source, desired managed state, policy, tests,
  pipeline definitions, review, and history.
- **Workflow:** Buildkite orchestrates reviewed CI, staging, promotion,
  protected deployment gates, approvals, queues, concurrency, and artifacts.
- **Runtime:** Docker and Compose provide reproducible execution and
  isolated supporting services.
- **Control/application:** Python 3.12 owns domain policy, target resolution,
  planning, risk, rollout, evidence, recovery decisions, and composition.
- **Source of truth:** NetBox owns infrastructure identity, topology/IPAM
  relationships, platform, role, tags, targeting, and inventory metadata. Git
  owns managed device-configuration intent. A managed property has exactly one
  authority, explicitly assigned before overlapping NetBox/native fields are
  consumed; devices provide observed state.
- **Secrets:** OpenBao AppRole supports bounded local-service authority, while
  protected Buildkite jobs use claim-bound OIDC workload identities and
  short-lived, single-use, exact-path tokens. Application models never embed
  secret values.
- **Assurance:** Batfish performs offline multi-vendor behavioral checks;
  protected promotion enforces plan-, policy-, snapshot-, and commit-bound
  assurance before any deployment authorization.
- **Digital twin:** Increment 8 uses Terraform with CiscoDevNet CML2 to own a
  separate personal-CML twin's infrastructure lifecycle, never production
  device configuration. See the
  [Terraform/CML digital-twin architecture](terraform-cml-digital-twin.md).
- **Execution:** Ansible Runner with `cisco.ios` remains the Cisco provider.
  Direct PyEZ/NETCONF preserves one Junos exclusive candidate session across
  pre-commit policy approval. Python decides what and why; adapters implement
  how without flattening vendor safety semantics.
- **Live validation:** future pyATS/Genie for Cisco and JSNAPy/PyEZ for Junos
  normalize into platform-owned results.
- **Audit/evidence:** `ChangeRecord` and `FleetChangeRecord` hold bounded
  execution evidence. Append-only `ChangeAuditRecord` and
  `ConfigurationObservationRecord` objects correlate protected delivery and
  private Oxidized chronology by stable identity and digest; see
  [Audit and configuration history](audit-and-configuration-history.md).
- **Continuous observability:** persistent Prometheus and credential-free
  Blackbox TCP probes run independently of CI. Stable NetBox identity names
  each series; private CML realization admission controls whether the
  NetBox-derived management endpoint is scheduled. Provisioned Grafana,
  reviewed Prometheus rules, private Alertmanager routing, and a bounded local
  receiver provide operator visibility without remediation authority. SNMPv3
  and gNMI/OpenConfig remain later increments. Oxidized remains the separate
  configuration chronology boundary.

Dependencies point inward to platform-owned policy and types; integrations
implement explicit boundary contracts. Provider details must not become domain
policy, and external observations must be normalized before policy consumes them.

## Implemented now

Architecture Baseline 1 and the first narrow Cisco IOS XE interface-description
vertical are implemented. Increment 3 adds the primary read-only NetBox inventory
path while retaining local YAML for isolated and offline work. OpenBao is the
primary credential path, with AppRole and exact KV-v2 retrieval behind the secret
boundary. See the [NetBox inventory provider](netbox-inventory-provider.md) and
[OpenBao secret provider](openbao-secret-provider.md).
Increment 4 adds the first Junos planning and transaction implementation. Cisco
configuration remains on Ansible Runner; implementation evidence required Junos
candidate transactions to use direct PyEZ so Python can approve the same locked
candidate before commit-confirmed. See the [Cisco](cisco-interface-description-vertical.md)
and [Junos](junos-interface-description-vertical.md) vertical documents.
Increment 5A adds [fleet rollout planning](fleet-rollout.md): narrow paginated
NetBox selectors, exact frozen membership including no-ops, nested child plans,
canonical fleet digests, deterministic representative canaries and waves, and
complete read-only fleet preflight. Increment 5B adds digest-approved sequential
execution of those exact cohorts through the unchanged single-device workflow,
strict `SUCCEEDED`-only continuation, honest stopped/partial evidence, and final
whole-fleet read-only desired-state validation. Live mixed-vendor acceptance and
process-local overlap admission are Increment 5C: a shared in-memory controller
atomically reserves complete stable device-identity sets, including no-ops,
across preflight, execution, and final validation. It is deliberately not a
distributed lock. Other named integrations remain future work.

Increment 7 is complete: protected promotion, Buildkite/OpenBao workload
identity, commit-bound least-privilege deployment, real personal-CML device
acceptance, independent validation, and same-build deployment retry hardening
are externally accepted. See the
[Buildkite live-deployment boundary](buildkite-live-deployment.md).
Increment 8 now provides the accepted Terraform/CML ephemeral staging
lifecycle. The manually owned two-router `NCDP Live` realization remains
outside Terraform; each staging run creates, validates, and destroys a separate
two-router realization with run-scoped state. See the
[Terraform/CML digital-twin architecture](terraform-cml-digital-twin.md).

Increment 10 provides durable append-only audit correlation and private
Oxidized Cisco/Junos configuration chronology, including accepted protected
PRE/write/POST correlation with causality explicitly not proven. See
[Audit and configuration history](audit-and-configuration-history.md).

Increments 11A and 11B provide the accepted continuous-observability plane:
credential-free management-service probes, persistent metrics, an immutable
Grafana dashboard, and advisory operator alerts. See
[Continuous observability](continuous-observability.md).
