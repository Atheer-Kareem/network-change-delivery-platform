# Protected profiled rollout execution

CAP-PROFILED-ROLLOUT Increment 5 composes the accepted current child lifecycles
with the [execution-admission foundation](profiled-rollout-execution-admission.md).
It does not confer capability acceptance. The capability remains **IN PROGRESS**.
Implementation tests use doubles and temporary stores; real execution requires
review, the separate hook activation below, merge and explicit human continuation.

## Protected authority and order

The existing planning and promotion steps retain their exact artifact contracts.
A separate runtime-gated group contains `profiled-rollout-human-authorization`
and `profiled-rollout-deploy`. Both are canonical non-PR main only. The human block
depends exactly on rollout promotion and has no fields. It cannot select targets,
interfaces, descriptions, profiles, device identities, canaries, waves, credentials
or recovery options. It approves only the exact frozen same-build promotion.

The deploy command reconstructs `authorize_rollout()` from the committed intent,
exact planning publication and parent bytes, exact promotion bytes and both
promotion digests, all 13 engineering receipts, Batfish/CML success and the
scheduler's unblocker UUID. The exact two fieldless graphs are independently
checked; a scheduler transition or self-digested authorization alone is insufficient.
A positively all-COMPLIANT parent returns before authorization, store execution
preparation, reservations, credentials, collection or chronology.

The protected wrapper uses `ncdp-deploy`, concurrency 1 and the existing
`ncdp/profiled-live-delivery` group. Neither automatic nor manual retry is allowed.
Rollout execution is not soft-failed. Only verified all-COMPLIANT no-write or
SUCCEEDED execution with final validation and durable parent readback returns 0.

```text
fieldless scheduler provenance + reconstructed authorization
→ structural create-only durable destination readiness
→ reserve every selected stable device, including COMPLIANT
→ complete fresh population preflight
→ frozen canaries sequentially → frozen waves sequentially
→ independent final whole-population D1 validation
→ durable parent publication/readback
→ release reservations
```

The single-target path acquires the same reservation after its existing
fieldless authorization and before LIVE trust/PRE/device activity, retaining it
through its existing durable publication and chronology. Its transaction,
promotion, outcome and historical evidence contracts remain unchanged. No lock
is held during either human pause. These are local advisory device locks, not
distributed locking, cross-host atomicity or fleet transactions.

## Child execution and failure truth

`execute_rollout()` sequences the exact frozen cohorts. Each DEPLOYABLE child's
original `artifact_bytes()` is strictly parsed and checked against its byte and
semantic digests and approved result. Those original bytes are separately
retained; no child reserialization substitutes for them. The existing
`execute_profiled_plan()` is called once and retains fresh JIT admission,
read-only prewrite observation, vendor-specific forward/inverse or confirmed
commit, independent POST and uncertainty rules. Complete population preflight
is an additional gate, not a replacement for child JIT validation.

Every child requires one validated target-bound Oxidized PRE before execution.
After entering the child execution boundary, one independent POST is attempted,
including when an unexpected exception escapes. Such an exception means execution
may have occurred; it does not fabricate a child result or imply zero writes.
COMPLIANT children never enter write cohorts and receive no execution chronology.
The parent `attempted` sequence records child lifecycle entry, not a write count.
Each child audit binds `child_lifecycle_entered=True` after validated PRE. Its
`write_attempted` is the verified child change record's `execution.attempted`: a
JIT stale or blocked result can prove False. If the child call escapes without a
valid record, both `write_attempted` and `final_outcome` are null (unknown), never
an invented True or False. The store independently verifies these facts against
the approved child and exact execution record. PRE/POST status fields use the
closed existing Oxidized observation-status vocabulary.

Only `SUCCEEDED` advances exposure. Every other current or future child outcome
stops later children, including RECOVERED, AMBIGUOUS, confirmation failure and
AUTO_ROLLBACK_PENDING. Earlier successful children are not rolled back. There is
no retry, resume or rollout-level recovery loop. Continuation requires a new
reviewed change and fresh planning.

A child evidence or POST chronology failure also stops exposure. Canonical child
records and exact source bytes are persisted, independently read back, correlated
in a rollout-child audit record, then linked from distinct rollout chronology.
Private PRE/POST/execution files and immutable partial store artifacts remain on
failure. Publication failure cannot replay a command. If the parent cannot be
established, the protected job returns nonzero and explicitly reports that child
evidence may establish a known or unknown device outcome, without a verified
durable rollout parent.

## Final validation and parent outcomes

`ProfiledRolloutFinalValidation` v1 independently re-resolves the entire current
population, re-expands the committed selection, requires the exact frozen
membership/order and device/interface/profile/operation/protection/credential
facts, loads all selected credentials, then observes every selected interface.
Original COMPLIANT children remain included. Positive child compliance artifacts
prove each reviewed desired description; their fresh timestamps are retained.
This module has no writer. It compares final D1, not the old pre-write description.

Parent outcomes remain distinct:

- SUCCEEDED: every DEPLOYABLE child succeeded and complete final validation passed.
- STOPPED: admission or execution stopped before any child successfully completed.
- PARTIAL: some, but fewer than all, deployable children succeeded before later
  exposure or evidence stopped.
- FINAL_VALIDATION_FAILED: all child transactions succeeded, but complete final D1
  was not proved. This grants no rollback, retry or additional write authority.
- EVIDENCE_FAILED: all deployable child transactions reported success, but required
  final/durable evidence was not established. This claims neither rollout success
  nor partial device delivery; no command is replayed.

Parent evidence identifies attempted, successful, compliant and untouched members,
the stopping member/reason/outcome, completed canaries/waves, remaining waves and
final validation when attempted. Artifact absence is never interpreted as compliance.

Every outcome requires child and chronology references in exact attempted-prefix
order. Preflight failure has no attempted children or references. PRE failure
requires complete evidence for all earlier entries, excluding the stopping child.
Child non-success and final validation require complete evidence for every entered
child. Only a separately recorded evidence failure can leave the final stopping
child incomplete; earlier children must remain complete.
`child_evidence_complete` records exact reference coverage; `evidence_failed`
records publication/chronology failure independently. A child call escaping and
subsequent evidence failure retain both uncertainty and evidence-failure facts.

## Distinct durable namespaces

`ProfiledRolloutAuditStore` adds optional namespaces without migrating historical
records: `rollout-records`, `rollout-child-records`, `rollout-chronology-records`,
`rollout-artifact-bytes` and `rollout-models`. Directories are private 0700;
regular create-only files are 0600, bounded and read back with exact identity and
hash checks. Semantic model storage and exact original bytes are distinct.
Existing canonical schema-v2 child plan/compliance/execution storage is reused.
Single-target promotion or audit envelopes are never invented for rollout children.

New frozen, extra-forbid v1 models are `ProfiledRolloutChildAuditRecord`,
`ProfiledRolloutChronologyRecord`, `ProfiledRolloutAuditRecord` and
`ProfiledRolloutDurablePublicationReceipt`. The parent ID is the deploy job UUID;
child IDs are UUIDv5(parent ID, stable device identity), with deterministic child
chronology IDs. Conflicting identities fail readiness before a write. Structural
readiness cannot promise later I/O success.

The parent binds build/pipeline/job/commit, original plan/promotion byte and
semantic digests, authorization/unblocker, preflight, frozen child bindings and
cohorts, outcomes and verified child/chronology references. Rollout chronology
references the independently read-back child audit, with TEMPORALLY_BRACKETED
relationship and **NOT_PROVEN** causality. Historical observation schemas are
unchanged. Same-build `profiled-rollout-durable-publication` is published only
after durable parent readback. Evidence Viewer adds a metadata-only rollout
index/detail route labeled current profiled rollout delivery. Parent digest means
the approved rollout planning digest; Rollout record digest identifies the durable
record separately. Lifecycle entry is never presented as a confirmed write count.
No credentials, raw configuration or original artifact bytes are displayed.

## CML availability risk and truthful diagnostics

Build #465 on `b24114c4fd4a14e931201a4510886bc714f89a03` had all engineering
receipts and Batfish success, but CML failed (exit 2, soft-fail presentation):
transit was second-BOOTED yet SSH/22 remained unavailable around 180.1 seconds.
Readiness was 3/4 and read-only validation 0/4. Cleanup, absence verification and
state retirement succeeded. Missing CML success correctly stopped rollout planning
before LIVE trust, NetBox, OpenBao or device collection; promotion did not run.

The one controlled unchanged-main reproduction succeeded with persisted
192.168.4.31 on Gi0/0 up/up, SSH v2, transit readiness and all four read-only
validations. The repeated historical failure's root cause remains **NOT PROVEN**.
The user accepted this bounded availability risk for continued implementation.
No staging lifecycle, timeout, persistence interval, recycle, image, profile or
topology change is made. Missing CML success still prevents rollout authority.

The receipt retrieval/validation boundary now reports `assurance prerequisites`.
`commit/context` remains for committed intent/context. The label changes no
retrieval, validation, ordering, retry or exit behavior. Missing CML reports:
`Profiled live plan FAILED — phase: assurance prerequisites. No device write.`

## Post-review activation and runtime acceptance

Do not activate during implementation. After review and explicit approval:

1. Verify the exact reviewed head and successful checks; confirm no protected
   ncdp-deploy job is running. Historical blocked no-authority/compliance tails
   alone are not active writes.
2. Capture existing hook SHA-256, owner/modes and profiled.env/persistent-pair hashes.
3. Install only the reviewed command-hook source into the existing agent-owned
   location. Retain owner; directory and hook modes must be 0700.
4. Independently verify installed bytes equal reviewed source and both environment
   and persistent-pair bytes are unchanged. On uncertainty, stop and inspect;
   never blindly repeat installation.
5. Do not change OpenBao policy/role or issue/rotate a SecretID. Exact 1/2/8/9
   authority is already active. Do not trigger a manual build.
6. Only after hook verification may the user merge. Let natural canonical main
   run to the rollout human block. Do not continue the single-target block.

Before any rollout continuation, show the exact build/commit, parent and promotion
semantic/byte digests, selected devices/interfaces, actual DEPLOYABLE/COMPLIANT
states and current → desired values, canaries/waves and Batfish/CML success.
The user manually decides whether to continue. Do not manufacture a change if
fresh planning is COMPLIANT. Runtime evidence, fault-injection review and explicit
user sign-off are still required for acceptance. Restore the temporary PR CML
exception before final integrated roadmap acceptance, per its existing exit
condition. CAP-OP-ASSURANCE remains DEFERRED; the exception remains ACTIVE now.

## Build #468 safety checkpoint and reviewed replan

Natural canonical-main [Build #468](https://buildkite.com/atheer-kareem/network-change-delivery-platform/builds/468),
UUID `01a087f4-0ae9-42e2-bc4a-aeaec2271deb`, ran commit
`69afe47c72d883f3e5edc9385160370d24038827`. The protected rollout consumer
successfully verified the actual downloaded promotion bytes and semantic digest,
reconstructed same-build promotion and fieldless authorization, and acquired the
complete stable-device reservation for devices 1/2/8/9. Actual consumer verification
closed the earlier external `read_artifacts` verification limitation.

| Retained rollout fact | Value |
|---|---|
| Authorization digest | `sha256:327a1c3cb0eb9c94a025550ebd9f97a84161b8763d747c6d315e9d8245e3bd2a` |
| Durable parent record ID | `01a087f4-1df6-443f-a118-c10559577f97` |
| Durable parent record digest | `sha256:0220aa240db9f29d6722b4e5309f8691768a1fa03640276e3b7c90d099be02be` |
| Outcome / stopping reason | `STOPPED` / `PREFLIGHT` |
| Preflight digest | `null` |
| Child lifecycles entered | `()` |
| Rollout writes | 0 |
| Untouched devices | 1 / 2 / 8 / 9 |
| `child_evidence_complete` / `evidence_failed` | `true` / `false` |
| Final validation | Not attempted |

The user also continued the separate single-target human block before rollout
deployment. That independently authorized change targeted `core-02`,
`netbox:dcim.device:1`, `GigabitEthernet2`, `netbox:dcim.interface:2`. Its approved
previous description was `None`; one forward write established
`ncdp-demo-reviewed-20260909`, independently verified by successful POST. The
single-target outcome was `SUCCEEDED`, with no recovery. This occurred before
rollout deploy, whose frozen child still expected current description `None`.

Build #468 had a sufficient independently established stale condition consistent
with the expected execution-basis rejection. The durable rollout parent records
only generic `PREFLIGHT` failure; it does not retain the exact thrown preflight
sub-check or prove an internal exception string. Fresh complete-population
preflight stopped exposure before any rollout child lifecycle or write, and the
durable STOPPED parent was established. No automatic retry or replay occurred.
This is positive runtime safety evidence, not successful rollout acceptance.

Build #468's frozen approval is obsolete. Do not retry, rebuild, resume, unblock
again, replay artifacts, repair devices or roll back to reuse it. The next reviewed
change instance is `CHG-PROFILED-ROLLOUT-20260910-R2`. Only the rollout change ID
changes: operation, selectors, interfaces, desired descriptions, wave size and
cohort derivation remain identical. Core/edge/IOS descriptions remain respectively
`ncdp-rollout-reviewed-core-20260909`, `ncdp-rollout-reviewed-edge-20260909` and
`ncdp-rollout-reviewed-ios-20260909`.

Fresh natural canonical-main planning after merge must establish the new observed
execution basis (D0); no current-description assumption is encoded. Core Gi2 may
now be observed at the verified single-target demo value, while the other three
interfaces may still have no description. Both are expectations, not new evidence.
This execution basis is separate from B5 accepted managed-state advancement.

The single-target intent remains unchanged at `ncdp-demo-reviewed-20260909`.
Its next fresh planning result is expected to be COMPLIANT because the previous
POST established that value, but only fresh planning can prove compliance.
Positive compliance creates no promotion/write authority, reducing the chance
that this path changes rollout D0 again. Leave the single-target human block
untouched during the next runtime procedure regardless. Review the new rollout's
actual frozen facts before manually authorizing it; never manufacture drift.
CAP-PROFILED-ROLLOUT remains IN PROGRESS.
