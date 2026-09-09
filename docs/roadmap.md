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
| CAP-RUNTIME-VERIFY | Verified profiled deployment runtime | ACCEPTED |
| CAP-DOCS-TRUTH | Current architecture, acceptance and demo reconciliation | ACCEPTED |
| CAP-OUTCOME-TRUTH | Truthful profiled delivery outcomes | ACCEPTED |
| CAP-DURABLE-EVIDENCE | Durable schema-v2 delivery evidence | ACCEPTED |
| CAP-CONFIG-CHRONOLOGY | Independent PRE/write/POST chronology | ACCEPTED |
| CAP-POPULATION-SCOPES | Population-derived admission and realization | ACCEPTED |
| CAP-INTENT-DELIVERY | Intent-selected generic delivery | ACCEPTED |
| CAP-PROFILE-REUSE-WRITE | Profile-reuse interface-description admission | ACCEPTED |
| CAP-PROFILED-ROLLOUT | Bounded profiled multi-target rollout | IN PROGRESS |
| CAP-OP-ASSURANCE | Operation-bound service assurance | DEFERRED |

CAP-RUNTIME-VERIFY, CAP-DOCS-TRUTH, CAP-OUTCOME-TRUTH, CAP-DURABLE-EVIDENCE,
CAP-CONFIG-CHRONOLOGY, CAP-POPULATION-SCOPES, CAP-INTENT-DELIVERY and
CAP-PROFILE-REUSE-WRITE are accepted;
other approved capabilities await their own tasks.
The temporary PR/development CML exception remains ACTIVE and unchanged.

### CAP-RUNTIME-VERIFY — Verified profiled deployment runtime

- **State:** ACCEPTED; implementation merged and explicitly reviewed/accepted by the user.
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
- **Acceptance/sign-off:** explicit user review and acceptance supplied at the
  start of CAP-DOCS-TRUTH, after merge of
  [#140](https://github.com/Atheer-Kareem/network-change-delivery-platform/pull/140)
  (`aa9b3c7`). Current CLI composition exercises failure before credentials or
  device activity, with no attempted write; Junos is unaffected and pins are
  unchanged. No LIVE write was needed: this is a local deployment-runtime
  prerequisite. Passing tests alone did not confer acceptance.

### CAP-DOCS-TRUTH — Current architecture, acceptance and demo reconciliation

- **State:** ACCEPTED.
- **Target/value:** README, current architecture/operations and readiness must
  describe implemented behavior and accepted positive/negative delivery paths,
  while preserving historical records. Make engineering capabilities discoverable
  without turning README into an implementation diary.
- **Acceptance criteria:** current/historical boundaries and evidence sources
  are explicit; pending-runtime claims are reconciled with supplied acceptance;
  readiness describes current scopes; README links to authoritative detail.
- **Dependencies/scope:** source/test/acceptance review, README/current docs,
  architecture diagram and demo/readiness; presentation changes only.
- **Must not change:** historical evidence or schemas; no new runtime capability.
- **Origin/population effect:** reconciles documentation and demo integration;
  uses population/scope terminology without pretending code is generalized.
- **Implementation evidence:** current docs/readiness and architecture SVG are
  reconciled with source and the user-supplied
  [current main-delivery acceptance](acceptance/profiled-main-delivery.md).
  Historical records remain historical. No live acceptance is performed here.
- **Acceptance/sign-off:** the user reviewed and merged [#141](https://github.com/Atheer-Kareem/network-change-delivery-platform/pull/141)
  (merge `72e80d8`), including the final active-source docstring cleanup, and
  explicitly accepted this capability by moving on to CAP-OUTCOME-TRUTH.
- **Remaining behavior boundaries:** provider metadata and downstream
  no-plan presentation are addressed by CAP-OUTCOME-TRUTH; readiness still checks selected
  historical audit records, while current delivery/viewer integration awaits
  CAP-DURABLE-EVIDENCE. Fixed catalog/scope constraints and the fixed main target
  remain CAP-POPULATION-SCOPES and CAP-INTENT-DELIVERY respectively.

### CAP-OUTCOME-TRUTH — Truthful profiled delivery outcomes

- **State:** ACCEPTED.
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
- **Implementation evidence:** tri-state provider mutation metadata; independent
  `post_validation.changed`; bounded record consistency and exact record/plan
  verification; digest-bound `ProfiledComplianceRecord` plus same-build planning
  publication receipts. Offline CLI/provider/delivery tests cover both vendors,
  invalid records/bindings and compliant continuation without execution authority.
- **Acceptance/sign-off:** the user explicitly instructed that [#142](https://github.com/Atheer-Kareem/network-change-delivery-platform/pull/142)
  be treated as merged and accepted, including the static UI/planning-time
  observation amendment. Current main merge is `946178e`. No new LIVE acceptance
  is claimed.

### CAP-DURABLE-EVIDENCE — Durable schema-v2 delivery evidence

- **State:** ACCEPTED; explicitly accepted by the user after build 420 evidence review.
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

- **Implementation checkpoint:** Foundation: profiled durable envelope + AuditStore
  + viewer — merged in #143; the frozen contract remains authoritative.
  Envelope version 1 references current schema-v2 artifacts; historical schemas
  remain unchanged.
- **Integration checkpoint:** Buildkite publication integration implemented:
  pre-write durable destination admission and verified immutable plan/promotion
  inputs; EXECUTION and COMPLIANCE durable publication by `profiled-deploy`;
  same-build publication receipt after exact readback; read-only final evidence
  correlation. No post-command evidence failure replays a device command.
  Merged in #144; no live acceptance or operator configuration change was
  performed during implementation. Subsequent runtime acceptance is recorded below.
- **Remaining boundary:** no PRE/write/POST capture, store migration or broader
  promotion admission. Protected external AuditStore configuration must be
  supplied by the operator before deployment; it is not repository-managed.
- **Exact byte verification:** retain bounded validated original artifact JSON
  separately from canonical artifacts; compare hashes and typed content on
  persistence and reads. Canonicalization cannot prove the original byte hash.
- **Confirmed foundation proof boundary:** supports every currently representable
  delivery family: Cisco/core-02 promoted EXECUTION with complete plan/promotion/
  execution correlation, assurance and human authorization; Junos plan/execution
  canonical artifact persistence/readback and exact `verify_profiled_record_plan()`
  binding with current lifecycle semantics; and Cisco and Junos COMPLIANCE
  envelopes without promotion, authorization or execution claims.
- **Foundation-era promotion boundary:** at foundation acceptance, promotion
  admitted only core-02/device 1, so promoted Junos EXECUTION was not representable.
  CAP-INTENT-DELIVERY now supplies intent-bound selection and an offline promoted
  Junos durable-envelope proof. This does not rewrite the foundation evidence or
  claim a runtime Junos deployment.
- **Acceptance/sign-off:** explicitly USER ACCEPTED based on controlled
  [build 420](https://buildkite.com/atheer-kareem/network-change-delivery-platform/builds/420)
  on `main`, build UUID `01a07d93-7fe6-4064-8533-f79f427b5cca`, commit
  `98cdf4d1b4161466624bf202aec4d27a6f89b608`. The
  [durable-publication acceptance record](acceptance/profiled-durable-publication.md)
  preserves exact planning, envelope and receipt digests, step evidence, typed
  AuditStore verification and viewer privacy checks. Subsequent PR #145 changed
  only Batfish icon presentation and does not invalidate this evidence.
- **Runtime result:** `core-02 / netbox:dcim.device:1`, `GigabitEthernet2`, was
  already `managed-by-ncdp-profiled-demo` at planning observation
  `2026-09-07T20:45:34.499476+00:00`; desired description was identical and change
  required was `False`. COMPLIANT continuation produced no plan, promotion,
  `ProfiledChangeRecord` or deploy CLI invocation; write/recovery attempted and
  promotion minted were all `False`. One COMPLIANCE / COMPLIANT durable envelope
  was validated with authorization and assurance absent, exactly one compliance
  artifact, original planning bytes and credential-provenance binding verified.
  Historical records remained `11 → 11` with bytes unchanged; current profiled
  records moved `0 → 1`. Final evidence independently validated the same-build
  receipt, and the viewer preserved its metadata-only privacy boundary.
- **Acceptance boundary:** COMPLIANT durable publication is runtime-accepted end to end.
  EXECUTION durable publication remains comprehensively offline-validated and
  will receive supplemental runtime evidence on the next legitimate network
  write. No device change is required or should be manufactured solely for
  acceptance. The capability is accepted; supplemental evidence is not a pending
  acceptance condition.
- **Build caveat:** `quality-observability-runtime exit 4` occurred while the
  aggregate build passed. This does not invalidate CAP-DURABLE-EVIDENCE acceptance:
  COMPLIANT minted no promotion, consumed no deployment-assurance prerequisites
  and makes no claim that all assurance/engineering stages succeeded. No
  observability investigation, fix or new roadmap item is part of this closeout.

### CAP-CONFIG-CHRONOLOGY — Independent PRE/write/POST chronology

- **State:** ACCEPTED; explicitly reviewed and accepted by the user.
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

- **Implementation evidence:** separate current profiled chronology envelope and
  deterministic parent-derived identity; optional `profiled-observation-records/`
  namespace with exact current EXECUTION parent revalidation. The existing deploy
  boundary admits chronology storage and successful target-bound PRE before its
  single device command, attempts POST immediately even after command failure or
  uncertain start, and publishes the child only after durable parent readback.
  Exact PRE-after/POST-before binding rejects intervening history. Closed
  SUCCEEDED/PARTIAL/AMBIGUOUS status retains `NOT_PROVEN` causality. Same-build
  receipts and the existing viewer expose metadata only; COMPLIANCE performs no
  chronology access and reports NOT REQUIRED. See the
  [current chronology contract](architecture/audit-and-configuration-history.md#current-profiled-configuration-chronology).
- **Implementation acceptance:** merged PR #147, main commit
  `77b5a768ba259e99e02866d525819bf73b05f4d0`. Final validation: full local pytest
  **2,382 passed, 5 skipped**; focused chronology regressions **428 passed**;
  Docker quality **2,340 passed, 47 skipped**; relevant Ruff/format/diff,
  package, Ansible and static checks passed. The valid durable parent remains
  readable when chronology is invalid/unavailable. The current plane is pinned
  to repository `oxidized:ncdp-lab-actual-state`, group `managed`; historical
  chronology schemas, bytes and routes remain unchanged.
- **Runtime acceptance/sign-off:** the user explicitly accepted the capability
  after one real metadata-only core-02 observation and real AuditStore/viewer
  compatibility verification. See the
  [canonical acceptance record](acceptance/profiled-configuration-chronology.md)
  for exact observation identities, the supported stale-reconciler correction,
  unchanged store counts and evidence boundaries. No device write occurred.
- **Acceptance boundary:** the independent observation plane is runtime-verified;
  coordinator ordering, failure precedence, durability, receipt binding and
  no-replay behavior are comprehensively offline-validated in merged PR #147.
  Full integrated EXECUTION chronology will receive supplemental runtime evidence
  on the next legitimate network write. No device change is required or should
  be manufactured solely for acceptance. Supplemental EXECUTION runtime evidence
  is not a pending acceptance condition. Existing controller/readiness population
  constraints and fixed promotion authority remain unchanged.

### CAP-POPULATION-SCOPES — Population-derived admission and realization

- **State:** ACCEPTED; explicitly accepted by the user after implementation and
  controlled runtime review.
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
- **Implementation checkpoint:** public ordered population declaration and typed
  consumer scopes; exact NetBox resolution; scoped realization/trust, Oxidized,
  observability and service projections; derived staging topology/ownership and
  profile-selected IOSv recycle behavior. Synthetic 1/2/4/5-member and repeated-
  profile coverage is recorded in the [contract and audit](architecture/population-scopes.md).
  Current staging evidence is v3; the historical v2 reader remains intact.
  No real member, write admission or pipeline graph changed.
- **Acceptance:** merged PR #149, main commit
  `adb7532a0a52e07642d0aad1934b8f5e2cc20e1b`, and controlled main build 435
  established real population/scope resolution, exact LIVE topology/trust,
  reconciled Oxidized/observability and successful schema-v3 disposable staging.
  Merged synthetic tests prove variable cardinality and repeated profiles.
  Planning was COMPLIANT; no human continuation or device configuration write
  occurred. The user explicitly accepted this capability; a fifth real device
  is not required. See the [acceptance record](acceptance/profiled-population-scopes.md)
  for runtime correlation, topology-digest distinctions and preserved authority.

### CAP-INTENT-DELIVERY — Intent-selected generic delivery

- **State:** ACCEPTED.
- **Target/value:** a reviewed committed typed intent selects an explicit
  delivery target and binds it into planning/promotion. Generic control-plane
  and promotion types no longer encode the current demo target.
- **Acceptance criteria:** admitted alternative intents work without
  target-specific control-plane branches; unsupported targets fail; target and
  intent changes invalidate authorization; human authorization stays fieldless.
- **Dependencies/scope:** CAP-OUTCOME-TRUTH and population-contract alignment;
  intent/promotion models, delivery driver, demo data and tests.
- **Durable-evidence prerequisite:** broader promoted target selection under this
  capability now permits the offline Junos promoted EXECUTION proof with exact
  plan/promotion/authorization, durable byte correlation and chronology. The
  durable envelope remains schema v1 and promotion remains schema v2.
- **Must not change:** write eligibility, credential architecture or human
  approval into an unrestricted free-text target selector.
- **Origin/population effect:** generalizes delivery selection, independently of
  total managed membership; the existing demo can remain one committed intent.
- **Implementation checkpoint:** fixed-path bounded typed intent loading; exact
  intent/result binding at planning, promotion and deployment; schema-v2 promotion
  derives target/device/change from the plan; dynamic annotations. Offline tests
  cover alternative Cisco/Junos intents, both compliant paths, mutation rejection,
  promoted Junos durable EXECUTION and chronology. The committed core intent,
  operation admissions, credentials and pipeline remain unchanged. See the
  [intent contract and coupling audit](architecture/intent-delivery.md).
- **Acceptance/sign-off:** explicitly USER ACCEPTED after review of merged
  PR #151, main commit `67fb65478337dd53879b20b2f1ca16d335866d22`, and natural
  main build 439 (`01a080f0-ebcb-4e49-873d-d0ef5779f123`). The merged focused
  suite passed 380 tests, including alternative Cisco/Junos selection and
  promoted Junos durable EXECUTION/chronology offline. Real planning was
  COMPLIANT; all engineering stages, Batfish and real CML staging passed.
  Human continuation and device writes were absent; AuditStore hashes remained
  unchanged. Passing tests and merge did not confer acceptance; explicit user
  sign-off did. A LIVE Junos write is not required. See the
  [acceptance record](acceptance/profiled-intent-delivery.md) for exact evidence
  and preserved authority boundaries.

### CAP-PROFILE-REUSE-WRITE — Profile-reuse interface-description admission

- **State:** ACCEPTED.
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
- **Implementation checkpoint:** explicit IOSv/IOSvL2 interface-description
  operation admission reuses the Cisco adapter/renderer/collector/recovery
  lifecycle, with offline planning, one-shot execution, recovery, intent,
  durable evidence and chronology proof. Serialized schemas and profile catalogs
  are unchanged. Buildkite deploy credential policy remains devices 1/2 only.
  No real network write was performed during implementation.
  See [profile reuse](architecture/profile-reuse-write.md).
- **Acceptance/sign-off:** explicitly USER ACCEPTED after review of merged
  PR #153, main commit `2bdfd1a82add97ff74cf21426519c5c9ff9588f2`, merged
  lifecycle/evidence tests and successful real local IOSv/IOSvL2 read-only
  planning. Both schema-v2 plans validated; protected management interfaces
  were rejected before secret reference/load or device collection. Passing
  tests and implementation merge did not confer acceptance; explicit user
  sign-off did. No device write was required or manufactured. Protected
  Buildkite credential scope remains devices 1/2; expansion requires separate
  approval. Build 443 CML readiness failed, independently of its COMPLIANT
  planning result; neither implies CML success. See the
  [acceptance record](acceptance/profile-reuse-write.md) for exact evidence,
  credential-session retirement and unchanged AuditStore hashes. CML and
  observability operational findings remain separate follow-up work.

### CAP-PROFILED-ROLLOUT — Bounded profiled multi-target rollout

- **State:** IN PROGRESS.
- **Scope approval:** the previous USER APPROVED contract was materially amended;
  the user explicitly approved the amended scope below, including the exact
  current-lab protected credential expansion. The approved scope is unchanged.
  Increment 1 begins implementation; tests and merge do not confer acceptance.
- **Target/value:** restore controlled multi-target delivery through the current
  schema-v2 profiled architecture. A reviewed rollout intent selects a bounded
  subset of the Git-declared managed population. Resolution freezes exact device
  and interface identities, child planning/compliance results, rollout policy,
  canaries, waves and execution order before any write. The rollout layer owns
  **who and when**; existing profile-specific child lifecycles own **how**.
  Schema-v1 fleet execution remains historical.

#### Increment 1 implementation checkpoint

The [read-only planning foundation](architecture/profiled-rollout-planning.md)
implements explicit-set selection, independent injectable credential admission,
complete current schema-v2 child planning, exact child-byte/result binding and
immutable canaries/waves/order. It returns a parent planning artifact or positive
all-compliant result, with no execution surface. No real network operation or
protected credential expansion was performed.

#### Increment 2 implementation checkpoint

The planning foundation accepts composable explicit members and closed typed
Git-population selector clauses using OperationalRole, NetworkOS and
AutomationProfileID. Each clause binds an exact reviewed interface and desired
description. Matching is fixed OR within each dimension and AND across
dimensions; filtered OR alternatives are valid, while zero-match clauses fail.
Expansion follows explicit-member order, then clause order, then Git declaration
order within each clause. Overlapping sources fail before child activity.
Selector-capable parent v2 binds instructions and exact expansion provenance;
merged explicit-only parent v1 bytes/digests and child-owned observation
timestamps remain unchanged. Matching Git population growth requires new
planning and independent admission, while nonmatching growth does not change
the bounded parent digest. This is still planning only.

#### Increment 3 implementation checkpoint

Repository implementation is complete: a fixed committed rollout intent, protected
all-member read-only planning, exact parent Buildkite publication and independent
same-build parent promotion. The explicit repository deploy credential definition
is now devices 1/2/8/9, and reviewed hook source admits rollout planning. Existing
single-target delivery and its fieldless human block remain unchanged. Rollout
stops at promotion, which grants no execution authority.

Protected external planning authority is **ACTIVATED and VERIFIED** against
reviewed runtime commit `a6dd4762b6ff022c30bd8bb4572571d149080995`. The reviewed
hook was installed and the exact read policy expanded once to 1/2/8/9; the
existing role and persistent pair were retained. See the bounded
[activation evidence](architecture/profiled-rollout-runtime-planning.md#verified-post-review-activation).
Natural canonical-main Build **#463**, UUID
`01a08609-fad7-4c4e-86c6-9d052420e8d8`, verified protected planning/promotion on
commit `97fb312cefa66b9716e1dcee33152404e6d3211a`: both jobs PASSED exit 0, not
soft-failed; all 13 engineering receipts and Batfish/real CML success were bound
to that build. The schema-v2 parent had four DEPLOYABLE children, canaries 1/2,
and waves [8], [9]. Exact semantic/byte digests and the artifact-LIST verification
limitation are recorded in the [runtime checkpoint](architecture/profiled-rollout-runtime-planning.md#increment-3-runtime-checkpoint).
The committed runtime had no rollout authorization or execution path. This is
Increment-3 evidence, not acceptance of the whole capability.

#### Increment 4 implementation checkpoint

The [execution-admission foundation](architecture/profiled-rollout-execution-admission.md)
implements a distinct verified fieldless authorization model/function, mandatory
exact promotion reconstruction, complete fresh whole-population preflight,
execution-basis staleness comparison and local stable-device overlap reservations.
Fresh observation timestamps may differ; classification, reviewed state and
identity/operation/credential basis may not. Existing child and parent artifact
bytes remain unchanged; future execution must pass original child artifact bytes.

Increment 4 introduced no execution surface. Its historical artifact bytes and
admission semantics remain unchanged in the following integration.

#### Increment 5 implementation checkpoint

The [protected execution integration](architecture/profiled-rollout-execution.md)
adds the fieldless rollout block, exact protected authorization reconstruction,
rollout and single-target stable-device reservations, whole-population preflight,
sequential frozen canaries/waves, original child-byte reuse and existing child JIT
execution. Every non-SUCCEEDED child stops later exposure. Independent final
whole-population D1 validation, distinct rollout child audit/chronology, durable
parent correlation/readback and metadata-only Evidence Viewer support complete
the implementation path. No rollout-level rollback, retry or resume is added.

Build #465's missing CML success correctly stopped protected rollout planning.
The unchanged-main reproduction succeeded; the repeated post-BOOTED IOSv SSH
failure remains ROOT CAUSE NOT PROVEN. The user accepted the residual bounded
availability risk for implementation. No staging timing/lifecycle change is
made. The prerequisite failure phase is now truthfully `assurance prerequisites`.

The execution hook was activated after review before PR #164 merged;
OpenBao authority required no change. Implementation/tests/merge are not capability
acceptance. Still required: controlled runtime evidence, fault-injection evidence
review, explicit user sign-off, and restoration of the temporary PR CML exception
before final integrated roadmap acceptance under its existing exit condition.
CAP-PROFILED-ROLLOUT remains IN PROGRESS; CAP-OP-ASSURANCE remains DEFERRED and the
temporary PR/development CML exception remains ACTIVE. No accepted state changes.

#### Build #468 runtime safety checkpoint and replan

Canonical-main Build #468 on `69afe47c72d883f3e5edc9385160370d24038827`
proved actual promotion consumer verification, fieldless authorization, complete
1/2/8/9 reservation and a durable `STOPPED` / `PREFLIGHT` result: zero child
lifecycles, zero rollout writes, all four untouched, no final validation and no
retry/replay. A preceding separately authorized single-target write changed core
Gi2 from `None` to `ncdp-demo-reviewed-20260909`, while the frozen rollout still
expected `None`. This independently established stale condition is consistent with
the expected execution-basis rejection; the retained parent does not identify the
exact internal preflight sub-check. See the [exact bounded evidence and next-run
procedure](architecture/profiled-rollout-execution.md#build-468-safety-checkpoint-and-reviewed-replan).

The obsolete Build #468 approval must not be retried or resumed. New reviewed
instance `CHG-PROFILED-ROLLOUT-20260910-R2` changes only the rollout change ID;
selectors, interfaces, desired descriptions and wave policy remain unchanged.
Fresh main planning establishes actual D0. The unchanged single-target intent is
expected to plan COMPLIANT, subject to fresh observation; leave its human block
untouched. This safety checkpoint does not establish successful rollout acceptance.
CAP-PROFILED-ROLLOUT remains IN PROGRESS.

#### Selection and independent authority

The reviewed rollout intent may contain an explicit target/interface set and/or
a closed typed selector resolved through current Git-declared population and
NetBox authority. It must not permit arbitrary NetBox queries, unrestricted
selector expressions, environment-selected or free-text targets, human-block
target selection, or discovery-driven authority. NetBox discovery alone never
admits a member.

Resolution must produce a non-empty exact frozen set with unique stable device
identities and unique stable interface identities. Unknown, ambiguous, protected,
mismatched or unsupported members block the whole rollout; they are never
silently removed. Every selected member independently requires:

1. Reviewed managed-population membership.
2. Explicit profile/operation admission for `interface_description`.
3. Explicit protected credential availability for that exact stable device.

```text
managed membership != protected credential authority != operation authority != rollout authorization
```

#### Explicit protected credential amendment

For the current four-device personal lab, the explicitly approved expansion of
`ncdp-buildkite-profiled-deploy` from exact credential reads **1 / 2** to
**1 / 2 / 8 / 9** is implemented and externally verified, with repository policy:

```python
DEVICE_IDS = (1, 2, 8, 9)
```

This is an explicit reviewed current-lab authority set. It must not be derived
automatically from managed population, observability scope, CML scope, Cisco
family, profile catalog or selector results. A future fifth managed device
receives no protected credential authority automatically.

The OpenBao policy must remain exact-path read-only: no wildcard, list, secret
write, auth-management or administrative capability. The existing persistent
deploy-agent identity was reused after verification. Repository policy and
installed protected authority now match the expanded exact set. This required
explicit post-review activation; repository implementation alone did not change
installed credential authority.

#### Complete planning and immutable rollout artifact

Before any write, planning covers the entire frozen selected population. Every
member is positively represented as either **DEPLOYABLE**, with one exact current
schema-v2 `ProfiledDeploymentPlan`, or **COMPLIANT**, with one exact current
schema-v2 `ProfiledComplianceRecord` and no write authority. Artifact absence
never means compliance. Any member failure blocks creation of a deployable
rollout artifact.

Each result binds exact device/interface identity, profile/NOS, endpoint,
operation admission, protection, credential provenance/reference, current
observation, desired state, child plan/compliance digest and exact child artifact
bytes. The future immutable profiled rollout artifact must bind:

- Source commit, rollout change identity and typed intent/selector.
- Exact frozen membership/order and stable device/interface identities.
- All child plan/compliance artifacts, their digests and exact bytes.
- Exact canaries, waves/execution order, rollout policy and parent canonical digest.

Unselected managed devices must not affect this digest. Moving a member between
COMPLIANT and DEPLOYABLE after approval invalidates the rollout. An all-compliant
rollout has positive typed compliance, no rollout promotion, no write
authorization, no execution, no recovery and no chronology.

#### Canary and wave policy

Canaries and waves are frozen before approval and never recomputed during
execution. Explicit reviewed canary selection is validated against the frozen
deployable population. At minimum, canaries represent each distinct
execution/recovery family present among deployable members. For the current lab,
when possible retain at least one deployable member outside the canary set so
the demo can show `canary → wave`.

Remaining deployable members use deterministic stable ordering and an explicit
bounded wave size. COMPLIANT members remain in the frozen population and final
validation but never enter write cohorts. Initial execution is sequential;
parallel device writes are not required.

#### Promotion, human authorization and pre-write admission

If any member is DEPLOYABLE, promotion binds the entire immutable rollout, all
exact child artifacts and current same-build prerequisites. One fieldless human
authorization approves **this exact membership, canaries, waves and child plans**.
It cannot select or change targets, interfaces, desired state, profiles, device
IDs, canaries, waves or credential scope. Any such change requires a new rollout
plan/promotion; credential-scope changes also require their own explicit authority.

Before the first write, independently revalidate intent/selector and frozen
membership; verify protected credential availability for every selected member;
complete read-only preflight for the entire selected population; and require
existing engineering/Batfish/CML same-build prerequisites, exact rollout
promotion, fieldless human authorization and durable evidence destination
readiness. Complete population preflight does not replace each child's fresh
just-in-time prewrite validation.

CML must publish its real same-build success receipt. Aggregate Buildkite
soft-fail presentation cannot substitute for CML success. Batfish remains
existing B4 service/network assurance, not exact candidate-write rehearsal.
CAP-OP-ASSURANCE remains DEFERRED.

#### Execution, parent outcomes and final validation

```text
approved frozen rollout
→ complete population preflight
→ canaries sequentially
→ waves sequentially
→ stop on every child non-success
→ final whole-population read-only validation
→ durable parent rollout evidence
```

Use current schema-v2 child transaction semantics. Each child receives its exact
approved plan/digest: one forward invocation maximum, no retry after uncertain
execution, independent POST, existing vendor-specific recovery eligibility and
no speculative recovery after ambiguity. Only child **SUCCEEDED** advances
exposure. Every other child outcome stops later exposure, including RECOVERED,
BLOCKED, FAILED, STALE, AMBIGUOUS and any other non-SUCCEEDED result. Earlier
successful members are not automatically rolled back.

The future parent must distinguish at least **COMPLIANT**, **SUCCEEDED**,
**STOPPED**, **PARTIAL** and **FINAL_VALIDATION_FAILED**. It must explicitly
identify attempted, successful and compliant members; stopping member/outcome;
untouched/unattempted members; completed canaries/waves; and remaining waves.
Stopped/partial execution still requires truthful parent evidence. It never
automatically resumes: continuation requires a new reviewed change and fresh
planning.

After all deployable children succeed, independently re-resolve and validate the
entire frozen population, including original COMPLIANT members. Failure produces
FINAL_VALIDATION_FAILED, with no automatic rollback and no additional write
authority.

#### Durable evidence and chronology

Preserve current child durable evidence and chronology. Executed children retain
schema-v2 execution evidence and applicable PRE/write/POST chronology; COMPLIANT
children retain compliance evidence and require no chronology. A future top-level
rollout evidence record references and verifies current child evidence rather
than duplicating child payloads.

Parent evidence binds rollout plan/promotion/authorization, selected population,
cohort order, child evidence identities/digests and parent outcome. Parent evidence
failure after possible child execution must never replay a child command.
Historical schema-v1 fleet models, commands and evidence remain historical only;
do not revive `fleet-plan`, `fleet-deploy` or legacy schema-v1 fleet execution.

#### Overlap admission

Future execution reserves exact stable device identities for the frozen
population before device activity. Reservation is device-based, not based on
interface, hostname or address. COMPLIANT members remain reserved because they
participate in complete preflight/final validation. Admission fails closed;
reservations release on every result/exception. No reservation is held across
the human-approval pause, so fresh revalidation remains required. Do not claim
distributed locking, cross-run atomicity or fleet-wide transactions.

#### Acceptance criteria

Eventual acceptance must prove:

- Deterministic exact frozen membership for explicit and selector-derived
  populations; protected, unsupported, unknown, ambiguous or mismatched members
  block the whole rollout.
- Positive COMPLIANT representation and reuse of current schema-v2 child plans;
  exact child bytes/digests are transitively approval-bound, with immutable
  canaries, waves and execution order.
- Complete preflight before the first write, with fresh child prewrite validation
  retained; every non-SUCCEEDED child stops later exposure.
- Explicit untouched members and partial outcomes, final frozen-population
  validation, and parent durable evidence binding child evidence/chronology.
- Exact overlap admission, no retry after child uncertainty, no automatic rollback
  of earlier successes, and zero write authority for an all-compliant rollout.
- Protected credential availability is explicit rather than inherited. For this
  lab, exact protected credential reads for **1 / 2 / 8 / 9** must be established
  while arbitrary devices remain denied.

A controlled real multi-target rollout is desirable for the final demo. Do not
manufacture unsafe/ambiguous failure on real devices to satisfy evidence;
fault injection/offline tests prove dangerous stop, partial and uncertainty paths.

#### Dependencies, implementation scope and exclusions

Dependencies are CAP-OUTCOME-TRUTH — ACCEPTED; CAP-DURABLE-EVIDENCE — ACCEPTED;
CAP-CONFIG-CHRONOLOGY — ACCEPTED; CAP-POPULATION-SCOPES — ACCEPTED;
CAP-INTENT-DELIVERY — ACCEPTED; and CAP-PROFILE-REUSE-WRITE — ACCEPTED.

Future implementation may include profiled rollout intent/selector, immutable
rollout planning artifact, explicit current device-1/2/8/9 protected credential
expansion, promotion/human-authorization composition, deterministic canary/wave
coordination, parent durable evidence, exact overlap admission, Buildkite
integration, tests and documentation. It restores controlled exposure over
explicit frozen subsets without a fixed population count.

Preserve independent operation authority and child transaction/no-retry
semantics. Managed membership never grants write authority. No wildcard
credentials, all-Cisco automatic admission, new write operation beyond current
admission, speculative retry, fleet-wide automatic rollback, distributed-locking
or fleet-atomicity claim, retired fleet runtime revival, historical evidence
rewrite, or false Batfish/CML candidate-assurance claim is permitted.
CAP-OP-ASSURANCE remains DEFERRED. The temporary PR/development CML exception
remains ACTIVE until its existing exit condition. Observability and CML repair
are not part of this governance amendment.

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
