# Authoritative capability ledger

This is the single signed-off ledger for NCDP refinement and restoration.
It tracks capability outcomes, not predicted PR counts. Approval below records
the user's explicit roadmap authorization; it does not claim implementation or
runtime acceptance. NCDP remains a production-inspired personal MacBook reference
implementation, not an enterprise deployment template.

## Governing architecture

```text
managed population
→ profile/capability projection
→ applicable validation/assurance
→ operation-specific execution authority
```

**Exact membership of an explicitly identified scope — not a permanently fixed
population size. Membership alone never grants write authority.**

Use managed population, profiled managed population, current lab population,
proof population, capability projection, realization scope, assurance scope,
delivery target and frozen rollout population in current architecture.
Exact selected membership, approved plans, artifact bytes, topology/scope and
profile/operation admission remain desirable invariants. Preserve explicit typed
catalogs and fail-closed admission; no dynamic plugin mechanism is proposed.

Historical exact-two/exact-four terminology, serialized schema identities,
accepted digests and acceptance records remain historical truth. ADRs and
implementation-history documents are evidence, not competing current roadmaps.

## Sign-off lifecycle

`PROPOSED → USER APPROVED → IN PROGRESS → ACCEPTED`

- **PROPOSED:** recorded for consideration; implementation is not authorized.
- **USER APPROVED:** the user approved the stated capability scope.
- **IN PROGRESS:** authorized implementation/review is underway.
- **ACCEPTED:** explicit acceptance evidence and user sign-off appropriate to
  the capability are recorded. Implementation, merge and passing tests alone
  do not establish this state.
- **DEFERRED:** deliberately postponed, with a reconsideration trigger.
- **RETIRED/HISTORICAL:** retained evidence without current runtime authority.

Material changes to approved scope return to user approval before that changed
scope is implemented. Attractive side issues are recorded as PROPOSED or under
an existing capability; they are not silently included in the active change.
One capability may span one or many PRs. Record implementation references and
validation separately from acceptance evidence and sign-off.

## Temporary development workflow exceptions

### Disposable CML staging on PR/development builds — ACTIVE

**User-approved temporary exception. Restore PR staging on explicit user request,
or before final integrated acceptance of the refinement roadmap. This is an exit
condition, not an optional follow-up.**

Disposable staging currently takes roughly 8–9 minutes at the end of PR
validation. PR builds cannot enter promotion/deployment, so no later PR step
consumes its success evidence. While implementing this roadmap, PR/development
builds skip disposable CML staging through the `cml-staging` scheduling condition:

```text
build.branch == "main" && build.pull_request.id == null
```

Canonical non-PR main retains the real staging lifecycle and same-build CML
success digest before schema-v2 promotion/deployment. No placeholder receipt,
fake artifact, path filter, authorization bypass or retry change is permitted.
Batfish and engineering validation remain. CML remains an assurance mechanism;
success is not guaranteed. This exception avoids repeated development execution
whose result is not consumed, without removing main assurance.

To restore PR staging, remove this temporary scheduling condition, update the
static pipeline contract and current workflow wording, and record the user's
request or integrated-acceptance restoration evidence here. Keep the original
staging dependencies, real success publication and main authorization checks.
See [workflow](architecture/buildkite-workflow.md) and
`tests/test_buildkite_pipeline.py`.

## Approved capability register

| Stable ID | Capability | State |
|---|---|---|
| CAP-RUNTIME-VERIFY | Verified profiled deployment runtime | IN PROGRESS |
| CAP-DOCS-TRUTH | Current architecture, acceptance and demo reconciliation | USER APPROVED |
| CAP-OUTCOME-TRUTH | Truthful profiled delivery outcomes | USER APPROVED |
| CAP-DURABLE-EVIDENCE | Durable schema-v2 delivery evidence | USER APPROVED |
| CAP-CONFIG-CHRONOLOGY | Independent PRE/write/POST chronology | USER APPROVED |
| CAP-POPULATION-SCOPES | Population-derived admission and realization | USER APPROVED |
| CAP-INTENT-DELIVERY | Intent-selected generic delivery | USER APPROVED |
| CAP-PROFILE-REUSE-WRITE | Profile-reuse interface-description admission | USER APPROVED |
| CAP-PROFILED-ROLLOUT | Bounded profiled multi-target rollout | USER APPROVED |
| CAP-OP-ASSURANCE | Operation-bound service assurance | DEFERRED |

Only CAP-RUNTIME-VERIFY, this ledger and the temporary scheduling exception are
in the current implementation scope. All other approved capabilities await
their own implementation task. Final acceptance/sign-off is pending for every
refinement capability below.

### CAP-RUNTIME-VERIFY — Verified profiled deployment runtime

- **State:** IN PROGRESS; implementation review and user acceptance pending.
- **Problem:** the retained exact Ansible collection verifier was historically
  enforced, but current profiled Cisco deployment did not invoke it.
- **Target:** Ansible-backed profiled deployment admits execution only when the
  actual effective Runner collection path contains exact repository pins:
  `ansible.netcommon == 8.6.0` and `cisco.ios == 11.4.2`.
- **Acceptance criteria:** exact pins/path pass; missing collections, wrong
  versions, malformed metadata, duplicate/ambiguous installations and invalid
  paths fail. Failure precedes credential loading, device collection and writer
  invocation; it is a bounded prerequisite failure with no attempted/ambiguous
  write, retry or recovery. Tests exercise the current CLI and prove Buildkite
  uses that same deployment entry point. Junos does not require Cisco runtime.
- **Must not change:** collection versions, installation behavior, credential
  architecture, write-device scope, Junos execution semantics, retries,
  population membership, operation admission or schema-v2 plan semantics.
- **Dependencies/scope:** retained verifier, selected Cisco adapter's effective
  root/path, profiled preflight boundary, focused CLI/adapter tests and direct
  operations documentation. No population generalization.
- **Origin:** restores a previously enforced prerequisite through current
  profiled architecture; no historical gate or executor is revived.
- **Implementation evidence:** `execute_profiled_plan` verifies the selected
  Ansible-backed runtime after digest approval checks and before preflight;
  `tests/test_profiled_runtime_admission.py` exercises real manifests through
  the CLI with external providers replaced by test doubles. The retained
  verifier checks path/manifest/version consistency, not cryptographic integrity
  of every installed collection file.
- **Acceptance/sign-off:** PENDING USER REVIEW. Test completion must not change
  this capability to ACCEPTED automatically. No LIVE deployment acceptance is
  authorized by the current implementation task.

### CAP-DOCS-TRUTH — Current architecture, acceptance and demo reconciliation

- **State:** USER APPROVED.
- **Target/value:** README, current architecture/operations and readiness must
  describe implemented behavior and accepted positive/negative delivery paths,
  while preserving historical records. Make engineering capabilities discoverable
  without turning README into an implementation diary.
- **Acceptance criteria:** current/historical boundaries and evidence sources
  are explicit; pending-runtime claims are reconciled with supplied acceptance;
  readiness describes current scopes; README links to authoritative detail.
- **Dependencies/scope:** source/test/acceptance review, README/current docs,
  architecture diagram and demo/readiness. This increment creates only the ledger.
- **Must not change:** historical evidence or schemas; no new runtime capability.
- **Origin/population effect:** reconciles documentation and demo integration;
  uses population/scope terminology without pretending code is generalized.
- **Recorded follow-ups:** old two-router demo checks, pending main acceptance
  prose, additive/v1-current architecture wording and implied current AuditStore
  integration belong here; they are deliberately not repaired in this change.

### CAP-OUTCOME-TRUTH — Truthful profiled delivery outcomes

- **State:** USER APPROVED.
- **Target/value:** distinguish compliant/no-change planning, blocked
  planning/authorization, execution attempt, provider-reported change metadata,
  unknown provider metadata and independently observed state transition.
- **Acceptance criteria:** coherent no-change delivery without fabricated plans
  or execution; failed planning cannot mean compliant; fix misleading
  `execution.changed`; enforce stronger execution-record consistency.
- **Dependencies/scope:** explicit semantics, bounded Runner-result investigation,
  planning/execution evidence, delivery driver and tests.
- **Must not change:** approval, stale-plan rejection, independent validation,
  uncertain-write/no-retry rules or historical record bytes.
- **Origin/population effect:** restores coherent no-write handling and corrects
  inherited evidence debt; semantics apply to any explicit target.

### CAP-DURABLE-EVIDENCE — Durable schema-v2 delivery evidence

- **State:** USER APPROVED.
- **Target/value:** persist current plan/promotion/execution/provenance through
  durable evidence storage and the existing viewer, using a bounded delivery/
  audit envelope rather than turning each device record into a Buildkite record.
- **Acceptance criteria:** current artifacts and correlation round-trip with
  schema/digest/identity verification; mismatched bindings fail; historical
  readers work; publication failures remain truthful and never replay a write.
- **Dependencies/scope:** CAP-OUTCOME-TRUTH; AuditStore, correlation models,
  delivery integration, viewer and tests, including pre-write store readiness.
- **Must not change:** device authority, privacy boundaries or historical schemas.
- **Origin/population effect:** restores durable correlation; target collections
  have explicit identities without permanent cardinality.

### CAP-CONFIG-CHRONOLOGY — Independent PRE/write/POST chronology

- **State:** USER APPROVED.
- **Target/value:** restore independent configuration-history correlation around
  current schema-v2 delivery once durable current parent evidence exists.
- **Acceptance criteria:** required PRE failure blocks before write; POST is
  attempted after execution where feasible; primary execution failure is
  preserved; immutable parent/child bindings express temporal correlation
  without falsely claiming causality (`NOT_PROVEN`).
- **Dependencies/scope:** CAP-DURABLE-EVIDENCE; profile-aware Oxidized capture,
  observation correlation, delivery integration and tests.
- **Must not change:** raw-configuration privacy, read-only history authority,
  no-retry/no-speculative-recovery semantics.
- **Origin/population effect:** restores chronology for explicit delivery
  subjects, not automatically the entire managed population.

### CAP-POPULATION-SCOPES — Population-derived admission and realization

- **State:** USER APPROVED.
- **Target/value:** remove unnecessary permanent-cardinality assumptions and
  duplicated instance knowledge. Supported-device additions normally require
  onboarding/data/trust/realization changes, not control-plane redesign.
- **Acceptance criteria:** multiple valid population sizes and multiple instances
  of one profile work; consumers require exact declared typed scopes; missing,
  extra, duplicate and mismatched members fail; staging ownership and cleanup
  remain exact. Membership never broadens write authority.
- **Dependencies/scope:** approved population contract; inventory/catalog,
  realization/trust, passive projections, staging inputs and contract tests.
- **Must not change:** operation allowlists, credential scope, current lab state,
  accepted boot workaround or historical serialized identities/digests merely
  for terminology. No arbitrary-device admission or dynamic plugin system.
- **Origin/population effect:** corrects current architecture coupling; this is
  the primary population-generalization capability.

### CAP-INTENT-DELIVERY — Intent-selected generic delivery

- **State:** USER APPROVED.
- **Target/value:** a reviewed committed typed intent selects an explicit
  delivery target and binds it into planning/promotion. Generic control-plane
  and promotion types no longer encode the current demo target.
- **Acceptance criteria:** admitted alternative intents work without
  target-specific control-plane branches; unsupported targets fail; target and
  intent changes invalidate authorization; human authorization stays fieldless.
- **Dependencies/scope:** CAP-OUTCOME-TRUTH and population-contract alignment;
  intent/promotion models, delivery driver, demo data and tests.
- **Must not change:** write eligibility, credential architecture or human
  approval into an unrestricted free-text target selector.
- **Origin/population effect:** generalizes delivery selection, independently of
  total managed membership; the existing demo can remain one committed intent.

### CAP-PROFILE-REUSE-WRITE — Profile-reuse interface-description admission

- **State:** USER APPROVED.
- **Target/value:** prove compatible profiles can reuse established Cisco
  adapter/renderer/collector/recovery families after explicit operation admission
  and acceptance. IOSv/IOSvL2 are initial proof subjects, not an architectural
  objective of making device IDs 8/9 writable.
- **Acceptance criteria:** prove interface/protection checks, artifacts,
  compliant/stale behavior, one-shot execution, inverse verification and
  uncertainty for each admitted profile; unsupported operations remain denied.
- **Dependencies/scope:** CAP-RUNTIME-VERIFY, CAP-OUTCOME-TRUTH; operation catalog,
  writer admission and profile tests; separately authorized image acceptance and
  any credential-scope changes.
- **Must not change:** population membership into write authority, all-Cisco
  admission, unrelated switch ACL capability or SNMP security requirements.
- **Origin/population effect:** adds accepted operation/profile combinations
  through reuse, not a new executor per device.

### CAP-PROFILED-ROLLOUT — Bounded profiled multi-target rollout

- **State:** USER APPROVED.
- **Target/value:** restore mature fleet safety through schema-v2 child plans.
- **Acceptance criteria:** freeze selected membership and compliant members;
  complete preflight before any write; deterministic canaries/cohorts/waves;
  controlled sequential exposure; stop on every non-success; explicit untouched
  members and partial outcomes; final validation of the frozen rollout population;
  accurately scoped overlap admission.
- **Dependencies/scope:** CAP-OUTCOME-TRUTH, CAP-DURABLE-EVIDENCE,
  CAP-POPULATION-SCOPES; profiled selector/plan/coordinator/evidence and fault tests.
- **Must not change:** child transaction/no-retry semantics or operation authority.
  Do not restore retired `fleet-deploy`; do not claim distributed locking or
  fleet-wide atomicity; earlier successes are not automatically rolled back.
- **Origin/population effect:** restores controlled exposure over explicit frozen
  subsets of the admitted population without a magic count.

### CAP-OP-ASSURANCE — Operation-bound service assurance

- **State:** DEFERRED until an actual service-changing write is selected.
- **Target/value:** bind normalized proposal/baseline/scope and applicable
  behavioral assurance to that operation when the write makes this necessary.
- **Acceptance criteria:** proposal, baseline or scope changes invalidate
  assurance; modeled/unmodeled limits are explicit; staging alone grants no write.
- **Dependencies/scope:** a separately selected service operation and its state/
  recovery contract; service planning, assurance and promotion integration.
- **Must not change:** current read-only B4/D1 proposals into write authority.
- **Origin/population effect:** restores useful operation-bound assurance through
  explicit service subjects rather than all managed devices.

## Historical evidence and deferred boundaries

Legacy schema-v1 single-device/fleet/protected delivery, SNMP provisioning
execution and exact-two staging are **RETIRED/HISTORICAL**. Keep compatible
evidence readers and fixtures; do not revive privileged executors. Relevant
evidence includes [fleet acceptance](acceptance/fleet-rollout-increment-5c.md),
[migration closure](acceptance/profiled-migration-closure-pr133.md),
[profiled deploy acceptance](acceptance/profiled-deploy-live-acceptance-pr132.md)
and [configuration chronology acceptance](acceptance/protected-configuration-observation-increment-10c7b.md).

Current single-target schema-v2 delivery, disposable staging, passive services
and B5 managed-state evidence are foundations to preserve, not proof that every
restoration above is already complete. The user has supplied positive main
delivery and negative fail-closed continuation acceptance; CAP-DOCS-TRUTH owns
their repository-wide reconciliation. No Buildkite runtime query is required
to implement this ledger.

Persistent live SNMP polling, gNMI/OpenConfig, distributed locks, enterprise HA,
dynamic plugins and extra staging optimization are outside current approved
implementation scope. New needs must be proposed explicitly.
