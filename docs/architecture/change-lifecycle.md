# Change lifecycle

The current protected Buildkite lifecycle binds review, execution, and evidence
to the same immutable single-device plan.

During Detour B3, the disposable CML step and complete protected-delivery group
are temporarily commented out together. The lifecycle below remains the
accepted design if the operator explicitly decides disposable CML staging is
useful again after its Terraform topology is ready for the intended profiled
population. Both blocks must be restored together; no protected live path is
active during the pause.

```mermaid
flowchart TD
  PR[Reviewed change] --> V[Visible validation gates]
  V --> VB[validation-complete]
  VB -->|runtime PR| PB[Profiled four-device PR Batfish assurance]
  PB --> PC[PR disposable CML staging]
  PC --> MR[Required Buildkite status / merge eligibility]
  VB -->|protected main| C[Main disposable CML staging]
  VB -->|protected main| B[Protected-main Batfish assurance]
  C --> P[Immutable promotion]
  B --> P
  P --> A[Human authorization]
  A --> G[Commit-bound deployment gate]
  G --> F[Fresh pre-write verification]
  F --> X[Vendor-aware single-device execution]
  X --> I[Independent post-validation]
  I --> E[AuditStore and Oxidized evidence]
  E --> M[Continuous monitoring]
  M -->|later problem| D[New reviewed restoration change]
  D --> V
```

Validation fails closed before privilege. Runtime-relevant same-repository pull
requests run offline Batfish assurance for the exact profiled four-device
candidate. Its current service stack is `routed_underlay, ospf, vlan, acl`, with separate
normalized service-subject digests, and it requires no
live inventory, credential, CML, trust, or device surface. Disposable CML and
the protected-delivery group remain paused. The profiled PR assurance artifact
is prevention evidence only and is not reused by the preserved legacy
protected-main branch.

The current protected promotion contains one `DeploymentPlan`. Planning records
canonical intent, inventory identity, preconditions, vendor-aware operations,
validation, and recovery expectations; its canonical digest binds the human
preview to machine execution. Batfish evidence is bound to the exact plan,
policy, baseline, derived candidate, and commit. CML staging proves the
independently disposable two-router runtime and real read-only provider paths;
it does not apply the proposed live plan.

Immediately before execution, fresh checks confirm commit, plan, target
identity, state, support, and still-required work. A stale, changed, missing, or
unsupported plan stops. The gate performs one vendor-aware device attempt;
ambiguous writes are not retried, and command success is insufficient because
independent post-change validation decides deployment success.

## Fleet engine boundary

Separately, the platform fleet engine accepted through Increment 5C supports
frozen fleets including no-op targets, representative canaries, bounded waves,
strict stop gates, honest partial evidence, and final whole-fleet validation.
The current protected Buildkite path does not promote or execute a fleet plan;
Buildkite fleet deployment remains unsupported/deferred. Neither the fleet
engine nor the protected path implies fleet-wide atomicity.

Immediate recovery uses proven vendor-native semantics for the supported
change. A later regression is handled as a new reviewed desired-state change
through the ordinary delivery lifecycle. Git revert may produce that proposed
Git change, but is history manipulation rather than device-change
authorization. Automated historical ancestry reconstruction, inverse
generation, and later-change conflict handling are deferred. Monitoring
continues independently after pipeline completion. See
[recovery safety](recovery-safety.md).

## Promotion before deployment

The currently disabled legacy immutable promotion downloads the exact
same-build `batfish-assurance`
artifact, independently verifies it against the checked-out plan, policy, and
baseline, packages the promotion, and records its digests. Human approval
authorizes that exact promotion. The serialized, non-retriable deployment gate
independently verifies the bundle and commit-bound live request before any
privileged device boundary. The active profiled PR artifact is deliberately not
compatible promotion input. Increment 7C live enforcement is accepted; a
corrected attempt always requires a new commit/build/authorization rather than
retrying historical work.
