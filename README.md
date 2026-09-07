# Network Change Delivery Platform

NCDP is a production-inspired personal Network Automation / NetDevOps reference
platform running on a MacBook CML lab. It is for learning, architecture
experimentation and portfolio demonstration, not a production deployment
template. It uses personal-lab data and infrastructure only.

It demonstrates a network change moving from reviewed intent to an independently
validated device write, with explicit boundaries between inventory, credentials,
assurance, human authorization, execution and evidence.

## Current architecture

![Current NCDP architecture: managed population and capability admission; continuing
engineering checks and network-model assurance; main-only disposable CML, immutable
schema-v2 promotion, human authorization and independently validated deployment; typed
artifacts and separate supporting audit/observability
planes.](docs/assets/ncdp-current-architecture.svg)

```text
managed population → profile/capability projection
                   → applicable validation/assurance
                   → operation-specific execution authority
```

NetBox owns stable device/interface and factual topology identities; CML owns
realization identities. Git-owned typed catalogs select profiles from explicit
platform/device-type facts, with no vendor-name guessing or fallback. Membership
never grants writes. The current implementation still binds a closed catalog;
[population
generalization](docs/roadmap.md#cap-population-scopes--population-derived-admission-and-realization)
is approved future work, not an already implemented onboarding promise.

| Current proof population | Profile/platform | Interface-description write admission |
|---|---|---|
| `core-02` · NetBox 1 | CAT8000V IOS-XE | Admitted; current main demo target |
| `edge-junos-01` · NetBox 2 | vJunos | Admitted through the current CLI |
| `transit-ios-01` · NetBox 8 | IOSv | Managed/read-only; operation denied |
| `access-sw-01` · NetBox 9 | IOSvL2 | Managed/read-only; operation denied |

## Current delivery

```text
engineering validation → Batfish assurance → disposable CML integration
→ schema-v2 live plan → immutable promotion → fieldless human authorization
→ independently revalidated profiled deployment → typed execution evidence
```

Canonical non-PR main follows this chain. PR/development builds temporarily
skip disposable CML under the [ACTIVE roadmap
exception](docs/roadmap.md#temporary-development-workflow-exceptions)
and have no delivery tail. Main still requires real same-build CML success.
Soft failure preserves downstream visibility; it grants no deployment authority.
Human unblock cannot repair missing prerequisites.

`ncdp profiled-plan` freezes exact identity, intent and execution/recovery
artifacts into a digest-bound schema-v2 plan. `ncdp profiled-deploy` requires that
exact approval, explicit LIVE authority and fresh preflight. Python owns policy;
Cisco uses Ansible Runner with an accepted exact collection-runtime prerequisite,
while Junos uses PyEZ/NETCONF, exclusive candidate validation and commit-confirmed.
Independent fresh post-observation decides success. Recovery preserves vendor
semantics: a bounded Cisco inverse or an unconfirmed Junos temporary commit,
never a generic rollback promise.

**Uncertain mutation → stop → no retry → independently reconcile.** Unsupported
operations fail closed. Buildkite independently revalidates promotion and human
authorization before the same CLI path. Its dedicated OpenBao AppRole uses a
persistent local SecretID and short-lived, one-use login tokens—an accepted
single-user reliability tradeoff. Historical deployment JWT/OIDC is retired;
separate staging JWT identities remain current.

## What has been demonstrated

The [current delivery acceptance](docs/acceptance/profiled-main-delivery.md)
records user-supplied positive and negative main-delivery evidence:

- **Authorized success:** core-02 interface description changed, independent
  post-validation observed desired state, and schema-v2 evidence reported
  `SUCCEEDED`, write attempted, recovery not attempted.
- **Fail-closed continuation:** failed prerequisites could leave the human block
  visible, but deployment independently returned `NO WRITE`; no execution record
  was fabricated.
- **Compliant planning:** source/tests establish that an already-compliant
  target produces no write plan. Its downstream presentation still needs
  refinement; devices must not be reset just to manufacture a demo change.

Current plans, promotions and execution records are typed artifacts. They are
**not yet integrated into the durable AuditStore/PRE-write-POST/viewer chain**.
The accepted record also exposes a known `execution.changed` metadata limitation;
its before/post observations prove the transition. Both gaps are explicit in the
[capability ledger](docs/roadmap.md).

## Engineering depth beyond the write

- **Managed-state reasoning:** D0 is accepted managed state, O is fresh observed
  state, and D1 is proposed state. Typed ownership envelopes distinguish drift
  from proposed change; description writes do not advance B5 D0.
- **Network assurance:** Batfish models routed underlay, OSPF, VLAN and selected
  ACL/service behavior. Its required success digest does not prove the exact
  interface-description candidate. Disposable Terraform/CML staging proves
  realization, management readiness, trust, read-only integration and cleanup;
  it does not rehearse the candidate write.
- **Independent operations:** NetBox, OpenBao, Ansible, Terraform and CML have
  distinct roles. Prometheus/Blackbox, Grafana/Alertmanager and private Oxidized
  config history continue independently of delivery, without remediation authority.
- **Testing:** extensive offline fault, identity, digest, transaction and pipeline
  contracts complement synthetic container/runtime integration and separately
  authorized live acceptance. SNMPv3 synthetic integration and historical
  provisioning are demonstrated; persistent live polling remains deferred.

Historical schema-v1 fleet/canary delivery, protected JWT deployment and durable
configuration chronology remain valuable [engineering
evidence](docs/architecture/audit-and-configuration-history.md),
with their executors retired. Current fleet rollout, service writes and broader
profile write admission are not implemented. No fleet-wide atomicity, enterprise
HA, production isolation or dynamic platform-plugin system is claimed.

## Explore

- [Architecture and subsystem map](docs/architecture/overview.md)
- [Delivery workflow](docs/architecture/buildkite-workflow.md),
  [lifecycle](docs/architecture/change-lifecycle.md) and [trust
  boundaries](docs/architecture/security-boundaries.md)
- [Current acceptance](docs/acceptance/profiled-main-delivery.md) and [demo evidence
  guide](docs/demo/evidence-package.md)
- [Managed state](docs/architecture/managed-state-drift.md),
  [Batfish](docs/architecture/batfish-assurance.md) and
  [observability](docs/architecture/continuous-observability.md)
- [Capability ledger](docs/roadmap.md) and [historical architecture decisions](docs/adr/)
