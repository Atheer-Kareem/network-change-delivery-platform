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
| CAP-CONFIG-CHRONOLOGY | Independent PRE/write/POST chronology | IN PROGRESS |
| CAP-POPULATION-SCOPES | Population-derived admission and realization | USER APPROVED |
| CAP-INTENT-DELIVERY | Intent-selected generic delivery | USER APPROVED |
| CAP-PROFILE-REUSE-WRITE | Profile-reuse interface-description admission | USER APPROVED |
| CAP-PROFILED-ROLLOUT | Bounded profiled multi-target rollout | USER APPROVED |
| CAP-OP-ASSURANCE | Operation-bound service assurance | DEFERRED |

CAP-RUNTIME-VERIFY, CAP-DOCS-TRUTH, CAP-OUTCOME-TRUTH and CAP-DURABLE-EVIDENCE
are accepted. CAP-CONFIG-CHRONOLOGY is the only capability in implementation
scope; other approved capabilities await their own tasks.
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
- **Promotion authority boundary:** the user confirmed that `ProfiledPromotion`
  continues to admit only the existing core-02/device-1 main target. Promoted
  Junos EXECUTION is **NOT CURRENTLY REPRESENTABLE**, not an incomplete vendor
  implementation. Its durable-envelope proof is deferred until
  CAP-INTENT-DELIVERY legitimately broadens promotion/intent admission. Evidence
  support must not broaden delivery authority to construct a proof fixture.
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

- **State:** IN PROGRESS.
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
- **Acceptance/sign-off:** pending user review and appropriate acceptance evidence;
  synthetic/offline validation does not confer acceptance. No live write is
  performed or manufactured in this increment. Existing controller/readiness
  population constraints and fixed promotion authority remain unchanged.

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
- **Durable-evidence prerequisite:** broader promoted target selection under this
  capability is required before a valid promoted Junos EXECUTION durable-envelope
  proof can exist. The CAP-DURABLE-EVIDENCE foundation preserves current admission.
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
